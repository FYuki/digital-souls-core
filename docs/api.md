# キャラクター推論API v0.1

Coreは人格文脈付きLLM Providerです。単独のチャットUI、配信フロントエンド、外部Agentの
いずれも同じAPIを利用できます。Agentループ、tool実行、記憶の保存、自動技能学習は行いません。
この版は**信頼された単一利用者のlocalhost専用**です。認証・tenant隔離・公開配信向けの
アクセス制御は未実装であり、インターネットや共有LANへ公開しないでください。

## 入り口

| メソッド・path | 用途 |
| --- | --- |
| POST `/v1/character/completions` | `character_id`で選択 |
| POST `/v1/chat/completions` | `model`に登録済みaliasを指定。同じapplication処理 |
| GET `/v1/models` | aliasの一覧。物理モデル一覧ではない |
| GET `/v1/characters/{character_id}` | version/profile/対応パラメータと設定済みモデル |

```json
{
  "character_id": "miori",
  "messages": [{"role": "user", "content": "こんばんは"}],
  "max_completion_tokens": 256,
  "stream": false
}
```

互換入口では`character_id`を`model`に置き換えます。内部character ID、config version、
inference profile、provider/modelは別の識別子です。返却JSONの`model`はSDKが返す実モデル表記を
保持し、aliasに書き換えません。レスポンスheaderの`X-Character-ID`、
`X-Character-Config-Version`、`X-Inference-Profile`で固定した設定を確認できます。
設定とカードは起動時に一度読み込みます。進行中の要求へ設定更新は入りません。

## 対応する小範囲

- textのみの`messages`（system/user/assistant/tool、1〜256件）。callerのsystemは
  人格systemの後に置きます。人格はLLMへの指示であり、セキュリティ境界ではありません。
- function型`tools`（name/description/parameters）、`tool_choice`のauto/none/required/名前指定。
  tool名は重複不可。tool callのID、名前、arguments文字列とtool結果は改変しません。
  argumentsをJSONとして解釈・実行しません。履歴中のcall IDは一意で、全結果が必要です。
- `stream`、`temperature`（0〜2）、`max_completion_tokens`（1〜32768）。
  旧`max_tokens`も同じ内部`max_completion_tokens`へ正規化します。両方指定は400です。
  上限はCoreの入力上限でありモデル能力ではありません。reasoningモデルでは非表示の推論tokenを
  含む場合があり、出力文字数の保証ではありません。providerへの変換はLiteLLMに任せます。
- 通常のchoices/message/tool_calls/finish_reason/usage、およびstreamのdeltaをそのまま返します。
  streamのusageはproviderが送った場合のみ保持します。Coreでtoken数を捏造しません。

各parameterは管理者がprofileの`allowed_parameters`で確認済みとしたものだけを許可します。
SDKにも`drop_params=False`を指定します。未知能力や未対応parameterは成功扱いにしません。
tools履歴の再送にもtools能力が必要です。`max_tokens`の許可名は正規化後の
`max_completion_tokens`です。認証情報、API endpoint、provider設定は要求から受け取りません。

Responses、multimodal、audio、developer role、JSON mode、stream_options、parallel_tool_calls、
n、seed、logprobs、その他未記載fieldは未対応です。unknown fieldは400、unknown endpointは404。
完全なOpenAI互換ではありません。必須クライアントがResponses専用なら別途実装が必要です。

## streaming・取消・エラー

SSEの`data: {chunk}`と正常終了時の`data: [DONE]`を返します。最初のchunkを待ってから
HTTP 200を開始するので、それ以前の失敗は通常のHTTPエラーです。途中失敗は
`event: error`＋`data: {"error": ...}`を送り、`[DONE]`を送らず終了します。
OpenAI Python SDKで途中失敗が例外となる契約テストがあります。すべての互換クライアントの
動作保証ではなく、独自clientはerror event・異常EOFを成功として扱わないでください。
初回chunk待機中も含め、切断・取消では上流streamをcloseします。
応答開始前に検出した切断は内部的に499/client_disconnectedとして扱います。
再試行・別モデルfallbackは実装しません。

エラーbodyは`{"error":{"type":"core_error","code":"...","message":"..."}}`です。
不正入力/未対応は400、送信policy拒否は403、unknown characterは404、provider制限は429、
provider失敗は502、timeoutは504。内部例外や入力・キーをerror本文へ反映しません。
本APIは要求/応答の保存・本文ログを行いません。運用時にSDKのdebugや外部callbackを有効化しないでください。

## 文脈・プライバシー

元Mioriカードを変更せず、name/description/personality/scenario/system_prompt/mes_exampleを
systemに組み立てます。Loreは最新user textに対する非再帰の単純key一致で、selective時には
secondary keyも必要です。insertion_order順です。これは汎用CCv3実装ではありません。
対応しないregex/constant/case-sensitive/配置/scan modeは起動時に拒否します。
first_mes、音声extension、creator_notesはモデルへ注入しません。

カードの`token_budget`は、この版ではモデル別tokenizerを使わないため強制しません。
注入system全体をUTF-8の`context_budget_bytes`で制限し、超過は切り捨てずエラーにします。
これは物理モデルのcontext windowではありません。metadataの物理token上限は未確認のnullです。
caller履歴の総token数を保証せず、providerの上限エラーはprovider失敗として返します。

`ContextSource`は固定したCharacter（ID/version/profile）と`AccessScope`を受け取ります。
初期実装は空で保存・検索・技能学習をしません。scopeはサーバー固定のlocal-operator/local/
local-privateであり、callerによるsubject/client/audienceの指定は拒否します。
将来、公開配信や複数利用者の記憶を扱うには、認証済みsubjectと信頼できるclient用途・audienceを
確立し、検索と外部送信の両境界で認可する実装が必要です。同じキャラクターIDだけで記憶を共有しません。

## 起動

Python 3.12.3、uv 0.8.22で`uv sync --frozen`を実行してください。
サンプル[設定](../examples/characters.json)は実モデル候補の書式例であり、利用資格や能力は未確認です。
`external_send_allowed=false`・許可parameterなしなので、そのままでは送信しません。
管理者が正当な利用経路・既存認証・対応モデルを確認した後だけ、git管理外の`*.local.json`で
profile/model/送信policy/能力を設定し、providerが規定する環境変数で認証を渡してください。
APIキーをJSON、prompt、リポジトリへ保存しないでください。サブスク契約をAPI資格と推測しません。

```sh
CORE_CHARACTER_CONFIG=examples/characters.json uv run --no-sync uvicorn digital_souls_core.api:create_app --factory --host 127.0.0.1 --port 8000 --no-access-log
```

環境変数なしならキャラクター0件で起動します。無課金のfake/SDK mock検証は`uv run --no-sync pytest`。
fakeの定型返答は人格品質や実モデル動作の証明ではありません。実モデル試験は未実施です。
