# Ollama native Chat検証（2026-10-03）

- 対象: PUBLIC `FYuki/digital-souls-core`, repository ID `1401730345`
- Issue: [#9](https://github.com/FYuki/digital-souls-core/issues/9)
- 基点main: `a7e220116287480d7171efda5986535ccd8839bd`
- 検証した実装revision: `61e4d63a787ccffd6b0604fa67841ce21dc147f7`
- この証跡は上記実装commitの後に追加する文書。証跡自身を実行対象revisionと称さない。
- Ubuntu/WSL、Python 3.12.3、uv 0.8.22、Node 24.19.0。
- LiteLLM 1.103.2 / OpenAI SDK 2.54.0、依存全体は同revisionのuv.lock。

## オフライン検証

実装commitと同一内容の作業treeでlint/type/UT/IT1を実行し、commit後に
lock・format・build・独立install・文書検査を実行した。

| 検査 | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS |
| `uv run --no-sync ruff check src tests` | PASS |
| `uv run --no-sync ruff format --check src tests` | PASS、19 files |
| `uv run --no-sync mypy` | PASS、19 source files |
| `uv run --no-sync pytest -m ut -q` | PASS、18件 |
| `uv run --no-sync pytest -m it1 -q` | PASS、100件 |
| `uv build --no-build-isolation` | PASS、sdist/wheel |
| CIと同じuv export/hash必須install/no-deps wheel install/isolated import | PASS |
| 必須Node reporterでdocs test 2ファイル | PASS、23件 |
| `node tools/check-docs.mjs` / `git diff --check` | PASS |

skip/xfail/xpassは0件。UT/IT1はsocket禁止で実LLMを使用しない。
更新当初は既存OpenAI stream timeoutの2件がFAILしたが、Python例外contextの
型による有界探索を追加した後、既存20件を含む上記全テストがPASSした。
StarletteのBlockingPortal非推奨警告とPydanticのTypedDict ReadOnly警告は残る。
警告を抑制して合格扱いにはしていない。

## 既存ローカル実モデル（IT2の限定範囲）

Ollama 0.32.5、`gemma4:12b`、11.9B Q4_K_M。
モデルmanifest digest:
`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`。
RTX 4070 Ti SUPER 16 GiB。モデル・認証情報を新設せず、既存のWSL loopback経路を使用した。
FastAPI TestClientによるプロセス内HTTP入力から、実LiteLLM SDKを通して既存Ollamaへ
ネットワーク通信した。外向きTCP配信を含むSTや他クライアントのE2Eではない。

公開Mioriカードを注入し、管理者profileは`ollama_chat/gemma4:12b`、
`ollama_think=false`、timeout 180秒、許可parameterはtools/max_completion_tokens/temperature。
要求はmax_completion_tokens=128、temperature=0。callerからproviderやthinkingを指定しない。

| 試験 | 結果 |
| --- | --- |
| 「接続確認完了」と短い一文を求める合成入力 | PASS、HTTP 200、非空content、finish_reason=stop、character=miori |
| 実モデル解決 | PASS、response model=ollama_chat/gemma4:12b |
| 通常応答usage | prompt 552 / completion 5 / total 557、約6.918秒（ロード時間込み） |
| 合成fixture_pingを一度要求 | PASS、単一call、非空ID、正しい名前、arguments={} |
| 同IDで合成結果`{"value":5}`を再送 | PASS、HTTP 200、TOOL_OK_5を確認、追加call 0、stop |
| 上流HTTPの構造監査 | PASS、全3要求think=false、toolsはnative field、format fieldなし、thinking文字数0 |
| cleanup | PASS、ロード済みモデル0件、ignored local configのexternal_send_allowed=falseへ復帰 |

toolは実行せず固定結果をテスト側が返した。応答本文・思考本文・私的会話・認証情報は
保存・コミットしない。記録は状態・件数・usage等の集計のみ。サービス設定は変更しない。

## 修正前との差と未検証

基点mainでは同モデルのthinking既定動作により256生成tokenが思考だけに使われ、contentが空だった。
上流done_reason=lengthをSDKがstopへ変換した。旧SDKのtemplateに依存するtools判定もfalseだったため、
暗黙fallbackを避けて旧Core tools試験はNOT RUN。今回、終了理由保持はmockで、通常応答と
native toolsはmockと上記実モデルで検証した。実モデルでのlength再現はNOT RUN。

人格品質、記憶永続化、他モデル/他providerの実呼出、Responses、Ollama streaming、
Docker/llama.cpp比較、外部配信STはNOT RUN。OpenAI streamingはmock HTTPのみPASS。
Ollama tool_choiceと旧ollama経路は非対応として送信前拒否を検証した。
物理context 262144、既存runtime context 4096、Core注入byte budgetは別物であり、
大contextでの推論能力や安全性をこの試験から推定しない。

最終PR headのCI結果はPRで確認・記録する。このローカル証跡はCI実行結果の代用ではない。

## 独立レビュー後の契約修正

修正実装revision: `f393201a2917a54510782a4979db160c2f411e55`。
初回の実モデル試験revisionとは別であり、この追補で実モデルを再実行したとは扱わない。

- SDKのreasoning_content等が入力Messageのextra=forbidと整合しなかったため、
  message/deltaを公開fieldに限定する。思考内容は保存・公開せず、reasoning-onlyの
  通常応答は空contentと元の終了理由を返す。
- Ollamaのthink=false/true/default全条件で、返却messageを加工せずtool結果と再送し、
  正常応答・call ID/引数/結果の保持、思考が応答にも再送payloadにも出ないことを確認。
- stream guardへtools/reasoning/api_base等の実要求条件を渡す。
  gpt-5.4 / gpt-5.4-mini / gpt-6-astraそれぞれ9条件で、実SDKの第2route判定を
  transport取得直前に観測し、Coreの拒否/通過と一致することを確認。
  endpoint条件は既定、管理者環境変数、SDK global、adapter引数を含む。
  api_baseやreasoningのcaller入力許可を追加したものではない。
- GPT-4o-miniのfunction tools付きnative Chat streamについて、実SDK＋mock HTTPで
  EOF/consumer close/cancelと非公開reasoning field除外を検証。

ローカルでは修正作業treeでUT 18・IT1 129・docs 23がPASS。その後、既存の
stream所有権テストをfunction tools付きに強化して同ファイル21件を再実行しPASS。
最終内容でruff check/format・mypy（20 files）もPASS。skip/xfail/xpassなし。
途中でSDK mock helperのimportがCoreのoffline metadata設定より先になり既存metadata検査が
1件FAILしたため、helperのSDK importをCore初期化後へ移し、対象68件と全suiteを再検証した。
最終head CIで全テストおよびpackage build/独立installを確認する。
実モデル・Docker・デプロイ・CodeRabbit再レビュー・マージはこの修正ではNOT RUN。
