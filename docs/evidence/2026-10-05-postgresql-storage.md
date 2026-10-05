# PostgreSQL 保存先の合成検証（2026-10-05）

対象: [Issue #43](https://github.com/FYuki/digital-souls-core/issues/43)、[ADR 0012](../adr/0012-postgresql-storage.md)。

## revision と環境

- 基点 main / epic: `c10bd09052dea26af81a7110e2ad1a9808c80236`。
- 実装 revision: `2b36064bb7d1231ede202b7aa6dadb101170501f`。以後はこの証跡と実行属性だけを整理。
- WSL Ubuntu の独立 worktree。Python 3.12.3、uv 0.8.22、Node 24.19.0。
- psycopg / psycopg-binary 3.3.6。既存依存を更新せず lock へ追加。
- PostgreSQL 18.6、公式 `postgres:18-bookworm`、digest
  `sha256:3725f4e2499eef5134592b3b4ab79a543ed7f8e533b05b5b637af926630f6650`。
- 合成 DB は `--network none`、公開 port なし、CPU 1 / memory 512 MiB、データは tmpfs、
  接続は専用の 0700 Unix socket ディレクトリのみ。実資格情報を使わず、稼働 DB へ接続しない。

## 結果

| 検証 | 結果 | 範囲 |
| --- | --- | --- |
| ruff / format / mypy | PASS | src/tests、54 files |
| UT | PASS | 114件、接続設定・factoryの拒否境界を含む |
| IT1 | PASS | 577件、既存 fake provider / SQLite 契約の回帰 |
| PostgreSQL 合成契約 | PASS | 41件、実 PostgreSQL 18.6 |
| 文書検証ツール | PASS | 23件、0件/skip/TODO/cancel失敗の回帰を含む |
| 文書参照・JSON・差分 | PASS | ステージ済み追跡ファイル |
| build / locked install / import | PASS | sdist/wheel、独立 venv、hash 固定 runtime 63依存 |
| 独立差分レビュー | PASS | 最新版の重大指摘なし。DB41件＋設定/factory84件を別途再確認 |
| 稼働 DB・dogfood・実モデル IT2/ST | NOT RUN | 今回の範囲外 |
| CodeRabbit 実レビュー | NOT RUN | draft feature→epic。skip 通知はレビュー完了ではない |

実行した主要コマンド（固定した uv / Node を PATH で解決）:

```sh
uv lock --check
uv sync --frozen
bash -n tools/start-llamacpp.sh tools/test-postgres.sh
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
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

独立 install では `-I` で site-packages 内の wheel 実体を読み、`create_app().title` と
PostgresConfig / Database / History / Memory、StorageConfig / Stores / open_storage の import を確認した。
検証用 hook で socket 接続・名前解決・psycopg 接続を拒否した状態でも import は成功した。
wheel SHA-256: `c833a516ecc5548c296f6230ec0c961449c2e37372d92e0c44f8bf18d1856523`。

## データと競合の確認

合成の履歴・記憶だけで、作成/再送/revision CAS、指定発話除外、private/解除/archive、
subject/client/character による分離、由来 ref/epoch/provenance、冪等 job、撤回後再構築を検証した。
private 化・削除と遅い記憶 commit の競合は両順序を検証し、`pg_locks` で待機が発生したことも確認した。
撤回途中の例外では履歴・派生本文・outbox が同時に rollback する。
空 schema 初期化/再open、初期化失敗の rollback、未知 version、型/default/追加relation、
PK/UNIQUE/FK/CASCADE 欠落の拒否を確認した。各ケースは固有 schema を終了時に削除する。

独立レビューでは FK 欠落により履歴削除後に turn 本文が残るケースを再現し、schema 照合の補強と
回帰テストで解消した。libpq の認証方式も固定し、暗黙の GSS/SSPI/OAuth 認証を拒否する。
schema 検査を追加した途中では PostgreSQL の制約表記差により 41ケースの setup が失敗したが、
修正後に全41件の成功を再確認した。途中の FAIL を PASS として数えていない。

## 制約

実データがないため SQLite 移送・backup・dry-run は実装しない。正本履歴の自動記憶化、
pgvector、永続 vector index、常駐 pool、稼働環境への適用も追加しない。
論理的な本文消去を WAL / backup / 物理媒体の消去保証とは扱わない。
通常の `create_app()` は保存無効のままで、trusted 起動側の明示接続・policy 注入が必要。
ライブラリの既知非失敗警告（Starlette の AnyIO alias、既存 Pydantic TypedDict ReadOnly）は残る。
CI の正確な head と run URL は PR 本文で追跡する。main は変更しない。
