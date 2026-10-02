# キャラクター推論API 検証証跡

- 対象: PUBLIC `FYuki/digital-souls-core`, repository ID `1401730345`
- 基点: `23d3c3f19ae988c023bdd665bf484b336549b339` (PR #2 merge)
- Issue: [#3](https://github.com/FYuki/digital-souls-core/issues/3)
- 作業branch: `feat/character-inference-api` → `epic/character-inference` → `main`
- 環境: Ubuntu/WSL2, Python 3.12.3, uv 0.8.22, Node 24.19.0
- 方針: [ADR 0001 (Proposed)](../adr/0001-character-inference-api.md)

## ローカル検証

初回37 testsから拒否・policy・token正規化・HTTP fixture・AnyIO取消scopeを追加し、
初回chunk前後のASGI切断を含む47 tests（skipなし）がPASSしました。ruff check/format、mypyもPASSです。
Pythonコード15ファイルが型検査対象です。文書requiredテスト23件、文書リンクと素材hash、
git diff --checkがPASS。CodeRabbit YAMLは取得した公式schemaで検証済みです。
最終revisionとGitHub CI結果はPRにhead SHAを添えて記録します。

```sh
uv sync --frozen
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync mypy
uv run --no-sync pytest -m ut -q
uv run --no-sync pytest -m it1 -q
uv build --no-build-isolation
```

sdist/wheelをbuildし、別venvへhash付きlock依存とwheelをinstallしてAPIをimportする手順は
[API CI](../../.github/workflows/api.yml)にあります。文書の既存required reporterも実行します。
Node配布は公式SHASUMS256との一致を確認しています。

外部clientとの実HTTP結合用に`tests.fixture_server:create_fixture_app`を用意しています。
checkoutで`.venv/bin/uvicorn tests.fixture_server:create_fixture_app --factory --host 127.0.0.1 --port 18080 --no-access-log`
を起動し、`character_id=miori`とゼロ引数tool `fixture_ping`を送ると、一度callを返し、
tool結果再送後に完了します。これも合成データのfixtureであり実LLMではありません。

## 確認範囲と不足

- fakeでMioriのsystem/personality/Lore注入、ID/alias共通処理、固定model/profile、通常chat、
  usage、tool choiceとID/arguments/result往復、text/tool streamを検証。
- SDK mock transport、OpenAI clientでstream途中errorが成功にならないこと、取消時closeを検証。
- unknown/unsupported、送信拒否、未知能力、context budget、内部errorの入力非反映、
  並行character分離・不変snapshot、caller scope拒否を検証。
- 実モデルIT2/ST: **NOT RUN**。利用資格・適切なモデルが未確認。キーの表示・転記や資格の新設なし。
- 実persona品質: **NOT RUN**。fakeの定型返答をLLM人格の成功として扱わない。
- 認証・公開配信のscope認可、記憶永続化・学習: **NOT IMPLEMENTED**。localhost単一利用者限定。
- CodeRabbit: PR #2では実reviewなし、0 starsで自動review無効の既知状態。
  main宛てPRでmanual reviewを依頼して実結果を確認するまで未完了。
- 保護/API権限/契約設定は変更なし。旧private repo・旧PR #28は対象外。

SDK整合のためLiteLLM 1.77.7とOpenAI 1.109.1を明示固定しました。
無制約の依存解決でOpenAI 3系列のHTTP型との不整合を検出したためです。
Starlette/AnyIOとLiteLLMの非推奨API警告は既知で、テストskipではありません。
これは依存の包括的なsecurity auditを実施したという意味ではありません。

## 親側独立reviewへの対応

PR #5の初期head `d356df29f52d2b720da569edc85492b5dae42add` に対し、次の2件を確認しました。

1. LiteLLM 1.77.7のAnthropic `ModelResponseIterator`はclose/acloseを持たず、
   `streaming_response`の行iteratorだけを閉じてもHTTPX Responseは閉じません。
   pinned SDK実オブジェクトとTracking AsyncByteStreamで再現しました。
   SDK内部のResponse所有関係を無理に追跡する実装を増やさず、ネイティブ`openai/`以外の
   streamはSDK呼び出し前に400/unsupported_stream_providerで拒否するよう制限しました。
   OpenAIについては実LiteLLM wrapper＋OpenAI SDK＋HTTPX MockTransportで、正常終了・
   consumer close・反復中の取消のすべてでResponseとwireがcloseされることを検証しています。
2. SDK反復中のHTTPX timeoutと`MidStreamFallbackError.original_exception`を型で分類するよう修正。
   初回chunk前のHTTP504、chunk後のSSE provider_timeout、秘密の例外文字列を返さないこと、
   wrapped rate-limit/未知errorも安全なコードへ分類することを検証しています。

これらは実LLM通信や課金なしのIT1です。provider全般の取消互換性を保証しません。
最新headのテスト・CI結果と親reviewの対応状況は修正PRに記録します。

再reviewで`openai/` prefix内にもResponses自動bridgeがあることを確認しました。
SDKと同じ`responses_api_bridge_check`を通信前に使い、ローカルmetadataが`mode=chat`で
モデル名を変更しない場合だけ許可します。`gpt-5-codex`、`o3-pro`、`codex-mini-latest`、
明示`responses/`と未知modeの拒否をpinned SDKの判定結果と比較しています。
正常経路のfixtureは既知Chatモデル`gpt-4o-mini-2024-07-18`を使い、実SDKが
`/v1/chat/completions`へ要求することとcloseをMockTransportで確認します。実LLMは呼びません。
