# 第2段階privacy境界の検証（2026-10-03）

## 対象

- Base main: `b8ddabd0c1cdedc8fd8f4a3bcd348ae9e8ec80ce`
- Code revision: `bbfe57c502218a776e3ed275462a5c68e59d96dd`
- Work: `feature/privacy-boundaries` → `epic/privacy-boundaries`
- [Issue #22](https://github.com/FYuki/digital-souls-core/issues/22)
- [ADR 0005](../adr/0005-privacy-boundaries.md)、[利用境界](../privacy.md)

## 環境とコマンド

WSL Ubuntu、Python 3.12.3、uv 0.8.22、Node 24.19.0。既存lockと依存を変更していません。
稼働中Core・llama.cpp・Ollama・GPU・常駐設定は操作していません。

```text
uv lock --check
uv sync --frozen
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync mypy
uv run --no-sync pytest -m ut -q
uv run --no-sync pytest -m it1 -q
node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
node tools/check-docs.mjs
git diff --cached --check
uv build --no-build-isolation
```

runtime依存を`uv export --frozen --no-dev --no-emit-project --format requirements-txt`で出力し、
独立venvへ`uv pip install --require-hashes`、wheelを`--no-deps`でinstall。
隔離Python `-I`でAPIとSQLite adapterをimportし既定appを生成しました。

## 結果

PASS: lint・format・mypy（35 source files）、UT **28**、IT1 **324**、文書 **23**、
sdist/wheel・独立locked install/import。skip/xfailは必須ゲートが拒否します。
既存Starlette/SDK/Pydanticの非推奨・型に関する警告3件は残ります。

privacy追加 **63件**は次を検証しました。

- 日英の合成credential/PII、NFKC/format文字/空白変形、nested JSON・JSON内Unicode escape。
- 一般的なpassword質問等の非検出と、無印opaque値を識別できない既知の限界。
- user/assistant/tool arguments/tool result/tool schemaの秘密値をDB・公開例外・logへ残さず、classifierへ渡さない。
- system/Lore/ContextSourceを含む合成後payloadも再検査。
- history/local/external/memory許可の分離、保存拒否と記憶拒否、scope分離、retry再認可。
- strict schema、未知/欠落/余分/重複キー、version不一致、矛盾分類、途中終了、複数choice、tool出力を拒否。
- timeout/cancelと、分類待機中のgrant撤回・policy交換、context前の再確認、history policy切断拒否。
- 既存LiteLLM/OpenAI SDKのlocal adapterを実行し、socket I/Oだけを合成応答へ差替え。
  loopback宛先、cloud credential/proxy不使用、transport closeを確認。実サービスへの通信ではありません。

独立レビューは最終privacy **63件PASS**、残blockerなし。
初回にはProfile再validate時のdefaultフィールドによる初期化失敗（22件FAIL）を修正しました。
初回lint/type不整合も修正済みです。独立レビューで指摘されたcontext前のpolicy交換と
履歴serviceが旧policyを保持する経路は再現・修正し、回帰で閉じています。

## 未検証・未実装

NOT RUN: 実モデルの機微分類品質、GPU推論、IT2/ST。mock成功を分類品質の保証とは扱いません。
secret/PII全般の網羅、未知の難読化、私的実会話、部分マスク、記憶抽出/検索、tenant認証は対象外です。
保存は明示注入・既定拒否を維持します。生ログや私的会話を証跡へ転載していません。
CodeRabbitの依頼・最終レビューとmain mergeは親タスクが管理します。
