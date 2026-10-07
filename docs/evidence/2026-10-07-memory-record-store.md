# 記憶の正本の保存port・PostgreSQL adapterの証跡

日付: 2026-10-07

対象: [Issue #72](https://github.com/FYuki/digital-souls-core/issues/72)

起点: `epic/memory-canonical-records` / `489e02d114d4824efb2d1d4332857282f0070122`

作業branch: `feature/72-memory-record-store`

## 実装範囲と設計

Issue全文、CONTRIBUTING、ADR 0016・0017・0019・0021と、2026-10-07の依頼に明示された
K1〜K5を照合した。PostgreSQLの保存境界だけを追加し、SQLite、逐語記憶の抽出・検索・consume、
SPECは変更していない。監督レビュー対応では、既存試験のschema_version期待値4箇所だけを5へ更新した。
push・PR作成・merge・private-knowledgeへの記録は未実施。

変更ファイル:

- domain port: `src/digital_souls_core/memory_record_store.py`
- adapter: `src/digital_souls_core/postgres_memory_records.py`
- 型の復元・正規化・日時範囲: `src/digital_souls_core/postgres_record_codec.py`
- v5表・列・厳密制約定義: `src/digital_souls_core/postgres_record_schema.py`
- 既存transaction内の撤回・本文消去: `src/digital_souls_core/postgres_record_revocation.py`
- 初期化・移行・厳密検証: `src/digital_souls_core/postgres_db.py`
- 新規DDLと既存revoke / revoke_turnsからの接続: `src/digital_souls_core/postgres_schema.py`
- port契約試験: `tests/test_memory_record_store_contract.py`
- 物理schema・移行・本文消去の試験: `tests/test_postgres_memory_record_schema.py`
- 設計文書: [memory.md](../memory.md)、[postgresql.md](../postgresql.md)
- この証跡

portのAPIは `register` / `get` / `list` / `head` / `affected`。
`RecordBatch` はEpisode・`FactWrite`・EpisodeFactLink・Semanticをまとめ、
`FactWrite.expected_version` は新規時None、更新時は現在版を指定する。
保存結果は本文なしの `RecordRef` のtuple、本文取得は既存domain型へ復元する。

承認済み8表に加え、冪等対応の永続化に `memory_record_registrations` を追加した。
ここには引用集合から作るキー、正規化登録内容の比較ダイジェスト、本文なしの結果参照だけを保持する。
比較ダイジェストは本文由来のためnullableとし、撤回した直接・依存の記録を結果に含む登録行でNULLにする。
登録行・キー・結果参照は保持し、NULLのダイジェストを持つキーでの再試行を内容にかかわらず拒否する。
本文消去と同一transactionで実行し、中断時にはダイジェストもrollbackする。無関係な登録は保持する。
キーへ生の履歴本文のhashを使わない。
引用表の `citation_role` で記録本体と5Wの明示理由を区別し、両方を検証・撤回する。
種別付き参照はnullableな所属ID列とCHECK・binding付きFKを組み合わせ、別Bindingへの参照をDBでも拒否する。

全表・列・型・参照・NULL消去対象は[PostgreSQL設計](../postgresql.md#正本記憶のschemaversion-5)、
API・冪等性・日時範囲・非復活は[保存契約](../memory.md#記憶の正本の保存port)に記載した。
期間検索の索引は追加していない。

## TDDの想定FAIL

契約試験28件、schema・移行試験19件（計47件）を、port・adapter・新規schema実装より先に作成した。
固定toolchainで `uv sync --frozen` 後、`bash tools/test-postgres.sh` を実行した。

実装前の結果（exit 1）:

```text
19 failed, 178 passed, 1340 deselected, 1 warning, 28 errors in 24.64s
```

- ERROR 28件: port fixtureの `PostgresMemoryRecords` moduleが未実装（ModuleNotFoundError）。
- FAIL 11件: 日時範囲・不正timezone・本文消去の試験で `memory_record_store` moduleが未実装。
- FAIL 5件: 新規schemaの改変試験で、対象の新規表がまだ存在しない。
- FAIL 1件: v4移行試験で、初期化後のschema_versionが4のまま（期待値5）。
- FAIL 2件: migrationのtable追加 / version更新が未実装で、注入した中断へ到達しない。
- 既存PostgreSQL試験178件はPASS。skip・xfail・dummy testは使っていない。

実装後、初期47件はすべてPASS。さらに直接抽出Semantic、別Bindingの参照、並行再試行・Fact CAS、
SQL書込後の登録中断、撤回中断、DBのbinding付きFK拒否を6件追加した（新規合計53件）。
これは追加の境界確認であり、初期のRED実行件数へ含めていない。

## 監督レビュー対応のTDD（追加7件）

修正起点: `ba46cac2566d3d9a91f43316696ae856981de4cb`。
追加試験だけを先に書き、実装修正・既存試験の版期待値更新より前に、同じ固定toolchainと
`TMPDIR=/dev/shm` で `bash tools/test-postgres.sh` を実行した（exit 1）。

```text
13 failed, 225 passed, 1340 deselected, 1 warning in 32.34s
```

追加7件のうち6件が想定FAIL、1件が既存処理でPASSだった。既存の版4固定assertionの7件もFAIL。

- `test_revocation_erases_only_affected_registration_digests[delete/private/turn_delete]` の3件:
  撤回後もダイジェスト文字列が残り、期待値Noneと不一致。
- `test_null_registration_digest_rejects_same_key_retry[False]`:
  未消去のダイジェストで旧結果の有効性照合まで進み、`memory_record_invalid` となった
  （期待はNULL登録の `memory_registration_conflict`）。
- `test_revocation_digest_erasure_rolls_back_with_history_and_records`:
  ダイジェスト消去SQLがなく、注入した `RuntimeError` が発生しなかった。
- `test_v5_rejects_nonnullable_registration_digest`:
  既存のNOT NULLがそのまま承認され、期待した `storage_schema` が発生しなかった。
- `test_null_registration_digest_rejects_same_key_retry[True]` は既存の内容不一致拒否でPASS。
  初期の想定FAILには数えない。

修正後は追加7件すべてPASS。撤回3経路で、直接のEpisode・Factと、別登録のFact旧版/新版・
依存link・根拠Episode由来Semanticを照合し、無関係なEpisode登録のダイジェストと冪等再試行を保持した。
行・キー・本文なしの結果参照の保持、NULLを含むv5再初期化も確認した。
消去SQL直後にNULLを確認してから中断し、履歴・全正本・イベント・登録行のsnapshotが完全に戻ること、
元の登録の再試行成功、その後の撤回成功を確認した。新規正本試験は合計60件。

## 受入条件の検証範囲

| 要件 | 主な試験 |
| --- | --- |
| 原子的登録 | 全種別のroundtrip、無効依存参照拒否、SemanticのSQL書込直後の中断で全新規行・冪等対応が0件、再試行成功 |
| 出典 | revision / epoch / message index / 話者 / 範囲 / private / 指定除外 / 確認保留 / 履歴削除 / 往復削除 / 別Binding、明示理由の引用も拒否 |
| 冪等性 | 同一結果返却、引用の順序・重複の正規化、同一キーで本文違いの409、同IDの別形成version拒否、並行二重登録防止 |
| Fact版 | 安定ID・v1旧版保持・v2取得・現在版一覧、期待版違い・版の飛越し拒否、並行CASは1件だけ成功 |
| Binding | 一覧・ID取得・根拠・link・event対応の除外/拒否、DBの複合FKでも別Binding拒否 |
| EpisodeEvidence | 引用SourceReference集合の完全一致、別Binding・欠落・版違いを拒否 |
| 撤回 | 会話削除・private化・選択往復削除で即時停止、依存link / Semantic停止、Fact全版停止、eventへ各版を紐付け |
| 本文消去 | 直接・依存の影響記録を結果に含む登録の比較ダイジェストNULL化、無関係な登録は保持。保存文・5W/日時/命題JSONB・experienced_at・日時範囲列のNULL化。消去前に型付き日時範囲が非NULLであることも確認 |
| 非復活 | private解除後の旧結果取得不可、旧IDの別出典登録拒否、冪等再試行拒否、停止Factへの版追加拒否 |
| 既存consumerとの分離 | consume後もaffected参照を保持。既存逐語記憶試験を変更しない |
| 日時 | 年/月/日/時/分/秒の全精度で3種別のJSONと型付き列を照合、閏年・半開終端・inclusiveな終点・Asia/Tokyo、不明とtimezoneなしはNULL、不正zone拒否 |
| 移行 | 凍結v4 DDLから5へ、既存全表の行を照合（履歴・逐語記憶・確認状態・tombstone等）、DDL後/版更新後のrollback・再試行、v5再初期化 |
| 厳密schema | 新規表の型・default・余剰列・CHECK / FK欠落の改変を拒否 |
| 撤回の原子性 | 本文消去SQL直後とダイジェスト消去SQL直後の中断でも履歴・記録・event・登録行すべてrollbackし、再実行で停止 |

## 品質ゲート

環境: uv 0.8.22、Python 3.12.3、Node v24.19.0、lock変更なし。
`TMPDIR=/dev/shm` を指定した（依頼の既存SQLite試験の環境要因回避）。
PostgreSQLは `tools/test-postgres.sh` のdigest固定公式18 image、network none・公開portなし・
一時Unix socket、合成データだけを使用。実データ・実LLM・資格情報は使用していない。

| コマンド | 結果 |
| --- | --- |
| `uv sync --frozen` | PASS、78 packages audited |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS、88 files |
| `uv run --no-sync mypy` | PASS、88 source files |
| `uv run --no-sync pytest -m ut -q` | PASS、477件（1101 deselected） |
| `uv run --no-sync pytest -m it1 -q` | PASS、863件（715 deselected） |
| `uv build --no-build-isolation` | PASS、sdist / wheelの2成果物 |
| `bash tools/test-postgres.sh` | PASS、238件（1340 deselected）、FAIL / SKIP 0件。新規60件は全PASS |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS、23件 |
| `node tools/check-docs.mjs` | PASS |
| `git diff --check` | PASS |
| IT2 / ST、実環境DBへの適用、実モデル評価 | NOT RUN |

必須試験のSKIP / xfailは0件。deselectedは別markerの試験で、SKIPではない。
UTには既存のDeprecationWarning 1件、IT1には既存のwarning 3件がある。
PostgreSQLにも既存のDeprecationWarning 1件がある。
PostgreSQLの合成試験の成功を、実運用・実モデルの受入として扱わない。

## 残件・判断に迷った点

監督の明示判断に従い、`tests/test_postgres_stated_at.py` の `SELECT version FROM schema_version`
期待値 `[(4,)]` の4箇所だけを `[(5,)]` に更新した。その他の既存試験の内容・期待値は変更していない。
初回実装で残った版固定由来の7 FAILと、レビューで判明したダイジェスト残存は解消し、
今回の必須ローカル品質ゲートはすべてPASS。実環境DBへの適用・IT2 / ST・実モデル評価はNOT RUN。
この証跡の今回の品質ゲートは `ba46cac` に監督レビュー修正を加えた差分を対象にしたもの。
公開先CI・PR・mergeは今回の実行対象外であり、未実施。
補助表・引用用途列・種別参照のFK表現は、承認済み設計を満たすための保存上の選択であり、
形成/保存判定・統合・再構成・索引など対象外の製品要件は追加していない。
