# 意味検索と PostgreSQL の統合検証（2026-10-05）

関連: [Issue #39](https://github.com/FYuki/digital-souls-core/issues/39)、
[#41](https://github.com/FYuki/digital-souls-core/issues/41)、[#43](https://github.com/FYuki/digital-souls-core/issues/43)。
構成と配備の境界は[統合ガイド](../semantic-postgresql-integration.md)を参照。

## revision

- main 基点: `c10bd09052dea26af81a7110e2ad1a9808c80236`。
- PR #42 → semantic epic の merge: `51054d3e4e86c95b6f6b60fde3be1f0e32123fb7`。
- PR #44 → PostgreSQL epic の merge: `075ebea4f42b9edd9a5f9a7b44261c8496e8de5b`。
- 両 epic を取り込んだ統合基点: `c9db2015652b84e44e971a1a12cd85ecff4a9fc2`。
- 統合テスト・文書・CI 修正: `d51841fe59e38db757eb40502f2707aec6d4ebd9`。

既存 main 向け統合 PR はなかった。新しい統合 epic と feature を独立 worktree で用意し、
両機能を保持して API CI と ADR 一覧の衝突を解消した。CodeRabbit 実レビュー・最新 head の CI は
main 向け統合 PR で追跡し、このローカル結果をレビュー完了として扱わない。

各 epic の merge 後 [意味検索 API CI](https://github.com/FYuki/digital-souls-core/actions/runs/37248970470)・
[文書 CI](https://github.com/FYuki/digital-souls-core/actions/runs/37248970504)、
[PostgreSQL API CI](https://github.com/FYuki/digital-souls-core/actions/runs/37248975741)・
[文書 CI](https://github.com/FYuki/digital-souls-core/actions/runs/37248975775) は PASS。

## 統合検証結果

WSL Ubuntu、Python 3.12.3、uv 0.8.22、Node 24.19.0、固定 lock を使用。
実 DB は PostgreSQL 18.6 の digest 固定公式 image で、network none・公開 port なし、
tmpfs と専用 Unix socket の使い捨て環境。稼働 DB・実資格情報・実モデル・GPU を使わない。

| 検証 | 結果 | 内訳 |
| --- | --- | --- |
| ruff / format / mypy | PASS | src/tests/評価CLI、65 files |
| UT | PASS | 216件 |
| IT1 | PASS | 746件 |
| PostgreSQL 契約 | PASS | 67件 = 既存41 + 同時利用26 |
| 文書ツール | PASS | 23件、参照・JSON・空白・差分 |
| build / locked install | PASS | 統合wheel、独立venv、hash固定runtime63依存 |
| offline 評価 | PASS | 合成fixture、quality_evidence=false |
| 独立統合レビュー | PASS | 未解決の重大指摘なし |
| 実モデル品質評価・実配備 | NOT RUN | 合成検証とは区別 |

追加26件は PostgreSQL 上の明示抽出から検索までを接続し、以下を確認する。

- 非文字列一致の順位と正の cosine、記憶 ID / source ref / epoch / provenance の保持。
- Binding の subject/client/audience/character の分離。
- private・履歴削除・指定発話除外・private turn・未抽出履歴を公式 SDK の入力に含めない。
- 空候補では embedding を呼ばず、検索中の source 撤回・store/設定世代変更を拒否する。
- 公式 SDK の model・次元・endpoint 不整合と、通常/stream 推論 dispatch 前の撤回を拒否する。

SDK経路はHTTP transportだけをfakeにし、実SDKの要求作成とJSON検証を通す。
実モデルの検索・分類・抽出品質を測った結果ではない。

```sh
uv lock --check
uv sync --frozen
bash -n tools/start-llamacpp.sh
bash -n tools/test-postgres.sh
uv run --no-sync ruff check src tests tools/evaluate-memory-search.py
uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py
uv run --no-sync mypy
LITELLM_LOCAL_MODEL_COST_MAP=True uv run --no-sync pytest -m ut -q
LITELLM_LOCAL_MODEL_COST_MAP=True uv run --no-sync pytest -m it1 -q
bash tools/test-postgres.sh
node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
node tools/check-docs.mjs
git diff --check
uv build --no-build-isolation
uv venv .package-check
uv export --frozen --no-dev --no-emit-project --format requirements-txt > .package-check/core-runtime.txt
uv pip install --python .package-check/bin/python --require-hashes -r .package-check/core-runtime.txt
uv pip install --python .package-check/bin/python --no-deps dist/*.whl
```

統合 wheel の SHA-256 は `7055a6037adce8452f34194c66845523a8335581ff4e5d8b93d26288e285f1d4`。
installed wheel の全 Python ソースと worktree が一致することを確認した。
`-I`、socket/名前解決/psycopg接続を拒否する検証 hook 下で、API生成と PG/storage/embedding/MemoryService の
import が成功した。同環境で offline 評価 CLI を実行し、`quality_evidence=false`、
`synthetic_only=true`、`backend_identity_verified=false` を確認した。

## 残る判断

通常起動は保存無効。配備には PostgreSQL の配置、専用 DB/role と権限・認証、Git外の明示設定、
store と policy を注入する trusted 起動 factory、embedding 対応モデル/endpoint の確認が必要。
実データがないため移送は不要。main マージ、dogfood変更、新資格情報・security設定は実施していない。
実環境の読取り調査結果は配備判断のため別途報告し、公開証跡へ私的設定を転記しない。
