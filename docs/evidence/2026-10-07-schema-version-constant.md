# PostgreSQL schema版定数の整理（2026-10-07）

対象は [Issue #82](https://github.com/FYuki/digital-souls-core/issues/82)、Epic #79。
起点は `924e2e0a86a4314a5626aa381e0901aa992e4014`、作業branchは `feature/82-schema-version-constant`。
SQLite撤去後のPostgreSQLだけを対象にした。SPECおよび製品の現状説明にあるversion 5は変更していない。
commitはこの証跡と同じcommitを参照する。push・PR作成・merge・Issue変更は実施していない。

## 変更と検証範囲

`postgres_schema.SCHEMA_VERSION = 5`を最新版の唯一の定義にした。
新規DDLの版登録、受け付ける最新版、最終移行の条件・版更新・検証はこの定数から導出する。
旧版1〜4は従来の明示定義で厳密に検証・段階移行する。
版5で正本表・制約が導入されたという構造の境界は数値5を維持した。
これらは「現在の最新版」を表すものではなく、次の版でも版5の構造を選ぶために必要である。

日時保存と旧抽出jobの機能試験からは不要なschema版比較を除いた。
新規作成・移行結果は定数比較とし、schema差異拒否後の版保存も定数比較で維持した。
旧fixture、移行前データ・receipt・fingerprint・日時・確認状態・epochの保持、
中断時の列・表・版・行のrollback、schema差異/未知版の拒否を検証するassertionとparameterは維持した。

環境はCPython 3.12.3、固定uv 0.8.22、Node 24.19.0、lock済み依存78 package。
固定toolchainをPATH先頭に置き、試験は指定されたメモリ上の `TMPDIR` で実行した。
PostgreSQLは `tools/test-postgres.sh` のdigest固定PostgreSQL 18、network none・公開portなしの
使い捨てコンテナとUnix socketで合成データだけを使用した。
実LLM・実環境IT2/STは **NOT RUN**。合成試験中の外部通信はなし。

## TDD と試験件数

1. 変更前：`uv sync --frozen`がPASS（78 package）。PostgreSQL全526件がPASS。
2. RED：既存の初期化・移行試験を先に定数比較へ変更した後、
   `uv run --no-sync pytest tests/test_postgres_history_initialization.py -q` を実行。
   製品定数が未定義なので `ImportError: cannot import name 'SCHEMA_VERSION'`、
   **FAIL（collection error 1件、実行試験0件）**。rollback等のassertionを変更していない。
3. GREEN：製品定数と導出を実装後、`bash tools/test-postgres.sh` が526件PASS。
4. 最終移行条件も定数へ整理し、後述の版6実験後に5へ復元して全品質ゲートを確認した。

| collection | 変更前 | 変更後 | 差分 |
| --- | ---: | ---: | ---: |
| UT | 462 | 462 | 0 |
| IT1 | 473 | 473 | 0 |
| PostgreSQL | 526 | 526 | 0 |
| 全体 | 1461 | 1461 | 0 |

前後に `uv run --no-sync pytest -m <marker> --collect-only -q` を実行した。
全体の `--collect-only -q` のnode IDを、下表の改名だけ正規化してソート比較し、1461件で完全一致した。
function数だけでなく各parameter付きnode IDが保存され、試験の削除・追加はない。
過去の日付付き証跡内の旧試験名は、その証跡のrevisionを指すため変更していない。
改名は現在版（v5）を名前に含む3件だけとした。移行元の版（v1〜v4）を名前に含む移行試験は、移行段階が固定で版を上げても変わらず、#86〜#88の対応表が参照するため、監督の判断で名前を維持した（実装担当が一度改名した8件を監督が元の名前へ戻した）。

| 旧名 | 新名 |
| --- | --- |
| `test_new_schema_is_v5_and_default_clock_is_current_utc` | `test_default_clock_is_current_utc` |
| `test_v5_schema_drift_rejected` | `test_record_schema_drift_rejected` |
| `test_v5_rejects_nonnullable_registration_digest` | `test_record_schema_rejects_nonnullable_registration_digest` |

## 版を6にした仮定の受入確認

これは版6の移行実装・受入ではなく、試験期待値の依存を調べる一時実験である。
実際の版6追加には版5の厳密検証と5→6移行が必要であり、今回追加していない。

方法：

1. `SCHEMA_VERSION = 5` の1行だけを一時的に `6` へ変更した。
   DDL・最新版の検証・試験の期待値は変更していない。
2. `tools/test-postgres.sh` のコピーで同じ隔離DBを作り、pytestの選択だけを変更した。
   下記7つの移行試験function（15ケース）を `--deselect=<node ID>` で除いた。
   ファイル名にmigrationが含まれていても、schemaの段階移行を扱わない機能試験は除いていない。
3. 残る511ケースを実行し、**511 PASS、950 deselected、FAIL/SKIP 0**。
   deselectedの内訳は他marker935ケースと移行15ケースであり、除外15ケースをPASSには数えていない。
   日時・往復削除・確認保留・schema差異/未知版拒否・新規初期化と再起動・抽出job等が含まれる。
4. 同じDB fixtureの隔離方法で、除外した移行試験のうち
   `test_v4_migration_rolls_back_and_retries[version]` を別実行した。
   **FAIL 1件**：`UPDATE schema_version SET version=5` による中断注入が、
   一時的な `version=6` と一致せず `DID NOT RAISE RuntimeError` になった。
   このFAILを製品版5の試験結果やPASSに混ぜていない。
5. `finally`で製品定数を5へ復元し、差分を確認して通常の全PostgreSQL試験を再実行した。

除外したnode ID（各functionの全parameter）：

- `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence`
- `tests/test_postgres_stated_at.py::test_v1_migration_interruption_rolls_back_and_retries`
- `tests/test_postgres_memory_record_schema.py::test_v4_migration_preserves_all_rows_and_reopens`
- `tests/test_postgres_memory_record_schema.py::test_v4_migration_rolls_back_and_retries`
- `tests/test_postgres_memory_confirmation.py::test_postgres_v2_migration_keeps_old_dates_receipts_and_does_not_scan_history`
- `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_preserves_stored_time_confirmation_and_receipt`
- `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_interruption_rolls_back_and_allows_retry`

静的確認は次の検索と、全PostgreSQL試験およびschemaを扱う製品コードの目視照合を併用した。
JSONの `memory-v1`、記憶recordの内容版、revision、日時、timeout、件数はPostgreSQL schema版ではないため区別した。

```sh
rg -n 'schema_version.*(\b5\b)|_tables\(5\)|def test_.*v[0-9]' tests --glob '*.py'
rg -n 'schema_version|SCHEMA_VERSION|_tables\(|_validate_schema\(|version (>=|<|==|in)' \
  src/digital_souls_core/postgres_db.py src/digital_souls_core/postgres_schema.py tests
```

結果：試験のschema版5の直書きは
`tests/test_postgres_memory_record_schema.py:121` の4→5段階のSQL照合1箇所だけ。
最新版の数値期待値と版番号入り試験名は0箇所。
最新版比較5箇所と初期化の表集合確認1箇所は定数参照、旧版・未知版の数値比較5箇所は維持した。
版6で書き換えを検討する期待値は移行中断のSQL照合1箇所だけで、機能試験の期待値は0箇所。
新規作成・再初期化の成功も511件に含まれ、定数がDDL/検証へ反映されることを確認した。

## schema版の直書き一覧

対象はschema版に関係するSQL、数値比較、表集合・検証への数値引数。
試験名は上の改名表で別記し、版と無関係の数値と現状説明のdocstringは数えていない。
行番号は変更前が起点commit、変更後がこの証跡と同じcommitに対応する。
許可版の列挙は1行単位で数えており、変更後には旧版の数値と最新版定数が共存する。

### 整理前（40箇所）

| ファイル:行 | 直書き箇所 | 整理・残す理由 |
| --- | --- | --- |
| `src/digital_souls_core/postgres_db.py:149` | `self._validate_schema(db, 5)` | 最新版の初期化・移行対象・最終検証。定数から導出へ置換。 |
| `src/digital_souls_core/postgres_db.py:154` | `if versions not in ([(1,)], [(2,)], [(3,)], [(4,)], [(5,)]):` | 許可する旧版1〜4の厳密列挙。最新版5は定数へ置換。 |
| `src/digital_souls_core/postgres_db.py:167` | `if version >= 5:` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_db.py:176` | `if version == 1:` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:178` | `db.execute("UPDATE schema_version SET version=2")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:179` | `self._validate_schema(db, 2)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:180` | `if version in (1, 2):` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:184` | `db.execute("UPDATE schema_version SET version=3")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:185` | `self._validate_schema(db, 3)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:186` | `if version in (1, 2, 3):` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:189` | `db.execute("UPDATE schema_version SET version=4")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:190` | `self._validate_schema(db, 4)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:191` | `if version < 5:` | 最新版の初期化・移行対象・最終検証。定数から導出へ置換。 |
| `src/digital_souls_core/postgres_db.py:194` | `db.execute("UPDATE schema_version SET version=5")` | 最新版の初期化・移行対象・最終検証。定数から導出へ置換。 |
| `src/digital_souls_core/postgres_db.py:195` | `self._validate_schema(db, 5)` | 最新版の初期化・移行対象・最終検証。定数から導出へ置換。 |
| `src/digital_souls_core/postgres_db.py:202` | `if (version >= 4 or table not in {"turn_tombstones", "turn_deletions"})` | 版4で導入した往復削除表の構造境界。維持。 |
| `src/digital_souls_core/postgres_db.py:203` | `and (version >= 5 or table not in COLUMNS)` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_db.py:216` | `if version == 1 and table == "turns":` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:218` | `if version < 3 and table == "turns":` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:276` | `and (version >= 5 or address != ("memory_events", "memory_events_binding_id_key"))` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_schema.py:159` | `"INSERT INTO schema_version(version) VALUES (5)",` | 最新版の初期化・移行対象・最終検証。定数から導出へ置換。 |
| `tests/postgres_v1_fixture.py:49` | `"""INSERT INTO schema_version(version) VALUES (1)""",` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_history_initialization.py:98` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_history_initialization.py:104` | `} == set(stores.database._tables(5))` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_memory_confirmation.py:152` | `db.execute("UPDATE schema_version SET version=2")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_memory_migration.py:962` | `assert db.execute("SELECT version FROM schema_version").fetchone() == (5,)` | 版と無関係の機能試験のため除去。新規版登録は初期化試験で確認。 |
| `tests/test_postgres_memory_record_schema.py:76` | `db.execute("UPDATE schema_version SET version=4")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_memory_record_schema.py:104` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_memory_record_schema.py:120` | `after == "version" and text == "UPDATE schema_version SET version=5"` | 4→5段階の版更新直後に失敗を注入するSQL照合。維持。 |
| `tests/test_postgres_memory_record_schema.py:131` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(4,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stated_at.py:105` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 版と無関係の機能試験のため除去。新規版登録は初期化試験で確認。 |
| `tests/test_postgres_stated_at.py:124` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_stated_at.py:179` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(1,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stated_at.py:197` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_stated_at.py:215` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(5,)]` | 新規作成・移行結果または拒否後の版保存を確認。定数比較へ置換。 |
| `tests/test_postgres_stated_at.py:225` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(1,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stores.py:416` | `connection.execute("UPDATE schema_version SET version=99")` | 未知版の拒否・保存を確認する合成値。維持。 |
| `tests/test_postgres_stores.py:422` | `assert connection.execute("SELECT version FROM schema_version").fetchall() == [(99,)]` | 未知版の拒否・保存を確認する合成値。維持。 |
| `tests/test_postgres_turn_deletion_migration.py:31` | `db.execute("UPDATE schema_version SET version=3")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_turn_deletion_migration.py:88` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(3,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |

### 整理後（28箇所）

| ファイル:行 | 直書き箇所 | 整理・残す理由 |
| --- | --- | --- |
| `src/digital_souls_core/postgres_db.py:154` | `if versions not in ([(1,)], [(2,)], [(3,)], [(4,)], [(SCHEMA_VERSION,)]):` | 許可する旧版1〜4の厳密列挙。最新版は定数比較。 |
| `src/digital_souls_core/postgres_db.py:168` | `if version >= 5:` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_db.py:177` | `if version == 1:` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:179` | `db.execute("UPDATE schema_version SET version=2")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:180` | `self._validate_schema(db, 2)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:181` | `if version in (1, 2):` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:185` | `db.execute("UPDATE schema_version SET version=3")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:186` | `self._validate_schema(db, 3)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:187` | `if version in (1, 2, 3):` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:190` | `db.execute("UPDATE schema_version SET version=4")` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:191` | `self._validate_schema(db, 4)` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:203` | `if (version >= 4 or table not in {"turn_tombstones", "turn_deletions"})` | 版4で導入した往復削除表の構造境界。維持。 |
| `src/digital_souls_core/postgres_db.py:204` | `and (version >= 5 or table not in COLUMNS)` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_db.py:217` | `if version == 1 and table == "turns":` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:219` | `if version < 3 and table == "turns":` | 旧版1〜4の段階移行・列構造・各段階の厳密検証。維持。 |
| `src/digital_souls_core/postgres_db.py:277` | `and (version >= 5 or address != ("memory_events", "memory_events_binding_id_key"))` | 版5で導入した正本表・UNIQUE/indexの構造を選択する歴史的境界。維持。 |
| `src/digital_souls_core/postgres_schema.py:12` | `SCHEMA_VERSION = 5` | 最新版の唯一の定義。 |
| `tests/postgres_v1_fixture.py:49` | `"""INSERT INTO schema_version(version) VALUES (1)""",` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_memory_confirmation.py:152` | `db.execute("UPDATE schema_version SET version=2")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_memory_record_schema.py:77` | `db.execute("UPDATE schema_version SET version=4")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_memory_record_schema.py:121` | `after == "version" and text == "UPDATE schema_version SET version=5"` | 4→5段階の版更新直後に失敗を注入するSQL照合。維持。 |
| `tests/test_postgres_memory_record_schema.py:132` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(4,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stated_at.py:178` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(1,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stated_at.py:224` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(1,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |
| `tests/test_postgres_stores.py:416` | `connection.execute("UPDATE schema_version SET version=99")` | 未知版の拒否・保存を確認する合成値。維持。 |
| `tests/test_postgres_stores.py:422` | `assert connection.execute("SELECT version FROM schema_version").fetchall() == [(99,)]` | 未知版の拒否・保存を確認する合成値。維持。 |
| `tests/test_postgres_turn_deletion_migration.py:31` | `db.execute("UPDATE schema_version SET version=3")` | 凍結した旧版fixtureまたは特定移行段階の準備。維持。 |
| `tests/test_postgres_turn_deletion_migration.py:88` | `assert db.execute("SELECT version FROM schema_version").fetchall() == [(3,)]` | 失敗・拒否時に旧版が保存されることを確認。維持。 |

## 最終品質ゲート

| コマンド | 結果 | 件数・成果物 |
| --- | --- | --- |
| `uv sync --frozen` | PASS | lockの78 package、差分なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS | 102対象Pythonファイル、違反0 |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS | 102ファイル |
| `uv run --no-sync mypy` | PASS | 102ファイル、問題0 |
| `uv run --no-sync pytest -m ut -q` | PASS | 462 passed、999 deselected、skip 0 |
| `uv run --no-sync pytest -m it1 -q` | PASS | 473 passed、988 deselected、skip 0 |
| `uv build --no-build-isolation` | PASS | sdist / wheel 2成果物 |
| `bash tools/test-postgres.sh` | PASS | 526 passed、935 deselected、skip 0 |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 27登録試験、skip/TODO/cancel 0 |
| `node tools/check-docs.mjs` | PASS | 追跡text・Markdown参照、違反0 |
| `git diff --check` | PASS | 未ステージ差分とstaged差分、違反0 |

依存に起因する既存warningはUT 1件、IT1/PostgreSQL 3件で、FAIL・SKIPではない。
GitHub CI・実CodeRabbitレビューは **NOT RUN**（push/PR操作は監督担当）。
確認事項：要件解釈の保留なし。実際の版6移行は今回の範囲外。
