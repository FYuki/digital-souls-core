# Issue #104 逐語記憶撤去の実装・試験証跡

日付: 2026-10-08

対象: [Issue #104](https://github.com/FYuki/digital-souls-core/issues/104) / [Epic #74](https://github.com/FYuki/digital-souls-core/issues/74)

起点: `origin/epic/memory-records-retrieval` / `ab47d16c23961b2d708281eacadc72fdc400b554`（#103 統合済み）

作業 branch: `feature/104-remove-verbatim-memory`

作業 worktree: `/home/asa/.t3/worktrees/digital-souls-core/feature-104-remove-verbatim-memory`

検証対象の実装・試験 commit: `d4be3880c10f2559455141c15ffacfd127189fa7`

## 実装と設計

Issue #104 の U6（再生成できない期間を許容）・U7（移行せず削除、backup 不要）・U8（評価ツールは最小追従）と、監督の6項目の設計どおり実装した。設計からの逸脱なし。新 ADR、構造化抽出、形成/新 consumer は追加していない。

- `postgres_schema.py`: `SCHEMA_VERSION = 6`。現行 `TABLE_COLUMNS` / `CONSTRAINTS` / `DDL` から逐語3表を削除。版5までの列・制約・index 名は `LEGACY_VERBATIM_*` として歴史的検証だけに保持する。`memory_events` の表・列・制約、履歴、確認保留、削除通知、正本の表の構造は維持。
- `postgres_db.py`: 旧版1〜4を従来どおり版5へ進め、5→6で `memory_sources` → `memories` → `memory_jobs` を DROP。`memory_source_lookup` は所有する表と一緒に削除する。schema advisory lock と同一 transaction 内で版更新・schema 検証を行う。段階的な移行元/構造導入の版1〜5は歴史的な数値のまま。5→6という移行先の6も固定し、新規作成・現在版検証には最新版定数を使う。
- `MemoryService`、`local_extractor.py`、`postgres_memory.py`、旧 `Memory` / `Candidate` / `MemoryJob` / `Evidence` / `MemoryStore`、`rank_memories` / `_tie_break` を撤去。`SourceVersion` は正本が使うため保持。`MemoryContext` は `memory.py` に残し、#103 の本文/guard を維持。
- `StorageStores` は `history` と `records: MemoryRecordStore` を返す。factory は同じ DB を使う `PostgresHistory` / `PostgresMemoryRecords` を構成。Python API の互換は作らない。
- `revoke` / `revoke_turns` は旧 `UPDATE memories` を削除し、event 挿入と `revoke_records` を維持。events/consume/pending/rebase/fail の旧消費 API は撤去。新消費 API はなし。
- `memory_evaluation.py`: JSON fixture の形式は変更せず、本文を `Episode.normalized_text` にした合成 `RetrievalCandidate` と citation を作る。created_at は fixture の文書順を表す固定の合成日時、最終言及は未知。`rank_records` に渡し、出力指標・`quality_evidence` を維持。`tools/evaluate-memory-search.py` の変更は不要だった。
- 試験の `register_sources` は合成 Episode を正本の register port に渡す fixture helper。製品の逐語抽出経路や LLM 抽出の代用 API を作ったものではない。残る確認保留・削除・競合の assertion を正本の記録に置き換えた。分類器が使う `structured_output.py` は変更なし。

## 変更・削除ファイル

以下は実装・試験 commit の全変更。証跡自身は別 commit。

- `D / src/digital_souls_core/local_extractor.py`
- `M / src/digital_souls_core/memory.py`
- `M / src/digital_souls_core/memory_contracts.py`
- `M / src/digital_souls_core/memory_evaluation.py`
- `M / src/digital_souls_core/memory_ranking.py`
- `M / src/digital_souls_core/postgres_db.py`
- `D / src/digital_souls_core/postgres_memory.py`
- `M / src/digital_souls_core/postgres_schema.py`
- `M / src/digital_souls_core/storage.py`
- `D / tests/fixtures/memory-protocol.json`
- `M / tests/memory_confirmation_contracts.py`
- `D / tests/memory_support.py`
- `D / tests/postgres_memory_support.py`
- `A / tests/postgres_query_support.py`
- `A / tests/postgres_record_support.py`
- `A / tests/postgres_v5_fixture.py`
- `R050 / tests/test_memory.py / tests/test_local_classifier_provenance.py`
- `M / tests/test_memory_evaluation.py`
- `M / tests/test_memory_ranking.py`
- `M / tests/test_memory_record_store_contract.py`
- `D / tests/test_postgres_batch_reads.py`
- `M / tests/test_postgres_history_initialization.py`
- `M / tests/test_postgres_memory_confirmation.py`
- `A / tests/test_postgres_memory_context_privacy.py`
- `D / tests/test_postgres_memory_migration.py`
- `M / tests/test_postgres_memory_record_schema.py`
- `D / tests/test_postgres_memory_recovery.py`
- `M / tests/test_postgres_record_retrieval.py`
- `M / tests/test_postgres_stated_at.py`
- `M / tests/test_postgres_stores.py`
- `D / tests/test_postgres_structured_memory.py`
- `M / tests/test_postgres_turn_deletion.py`
- `M / tests/test_postgres_turn_deletion_migration.py`
- `A / tests/test_postgres_verbatim_removal.py`
- `M / tests/test_storage.py`
- `R062 / tests/test_structured_memory.py / tests/test_structured_classifier.py`
- `M / tests/turn_deletion_contracts.py`

## TDD と中間 FAIL

版5→版6の新しい移行試験を実装前に追加し、変更前の `bash tools/test-postgres.sh` で **1 FAIL / 467 PASS** を確認した。FAIL は旧3表が残ることによる受入試験の失敗。その後、固定版5 DDLに逐語の memory/source/job、履歴、確認保留、正本 Episode/Fact/Semantic、通知と tombstone の非空データを投入する形へ拡充した。

実装途中の PostgreSQL は **30 FAIL / 364 PASS**（旧 helper の epoch 読取・旧 store の残存参照・canonical 表名の追従漏れ）、次が **1 FAIL / 1 ERROR / 390 PASS**（試験の import と parametrize の付け位置）。いずれも試験の追従を修正し、次の実行は **398 PASS**。mypy の中間型エラーも解消した。

`check-docs` は削除済み JSON fixture が index にまだ残っていた段階で **FAIL**（ENOENT）。削除を stage してから全追跡ファイルの検証を再実行し PASS。FAIL を最終 PASS と混同しない。製品文書の最小参照修正も必要なかった。

## 最終品質ゲート

固定 toolchain: uv 0.8.22 / Node 24.19.0 / Python 3.12.3、`TMPDIR=/dev/shm`。
PostgreSQL は `tools/test-postgres.sh` の digest 固定 PostgreSQL 18、network none、公開 port なし、専用 Unix socket、使い捨て DB、合成データのみ。

| コマンド | 結果 | 件数・補足 |
| --- | --- | --- |
| `uv sync --frozen` | PASS | 78 packages、lock 変更なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS | lint |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS | 100 files |
| `uv run --no-sync mypy` | PASS | 100 source files |
| `uv run --no-sync pytest -m ut -q` | PASS | 473 → 473（±0） |
| `uv run --no-sync pytest -m it1 -q` | PASS | 585 → 579（-6、逐語 extractor 専用） |
| `uv build --no-build-isolation` | PASS | sdist / wheel |
| `bash tools/test-postgres.sh` | PASS | 467 → 398（-81 +12 = -69） |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 27 → 27、skip/TODO/cancel なし |
| `node tools/check-docs.mjs` | PASS | 全追跡 text / local Markdown 参照 |
| `git diff --check origin/epic/memory-records-retrieval` | PASS | whitespace |
| `uv run --no-sync python tools/evaluate-memory-search.py` | PASS | fixture mode / `quality_evidence=false` / 5 queries / embedding 3 calls |
| 実 DB への適用 | NOT RUN | 使い捨て合成 DB のみ |
| IT2 / ST | NOT RUN | 実モデル・実環境受入は対象外 |
| remote CI / 監督レビュー | NOT RUN | 監督への引き渡し後に実行 |

SKIP / xfail / dummy test は追加していない。既存依存の Starlette 非推奨 alias と Pydantic ReadOnly warning は残る。
fixture の合成メトリクスを実モデル品質の PASS としない。PR #51 の評価再設計は未実施。

## PostgreSQL の受入範囲

- 凍結版5 DDLから版6へ、削除3表が無いこと、保持表の全行・全列が移行前 snapshot と一致することを検証。対象の主要表はすべて非空であることも確認する。確認保留の JSON と `memory_events` / `memory_event_records` の FK もそのまま保つ。移行後の正本候補の同一性と `MemoryRetrieval.search` を検証。
- 各 DROP の直後・版更新の直後の中断を4ケースで検証し、版5と全行の rollback・再試行を確認。
- 旧版1・2・3・4の既存移行試験は最新版6への到達を明示して保持。版4の「全行保持」は今回削除する3表を除いた保存対象について比較する。版4→5の中断時は旧3表を含む全 snapshot を保持する。
- 版6の新規 schema と再オープン、旧3表を追加した不正な版6の拒否、版5の旧列型・旧 FK・旧 index の drift の拒否を検証。
- 履歴削除/private化/往復削除/確認受入で event と正本撤回を維持。rollback、同じ Binding 内の登録/撤回競合、出典確認保留、残る turn、異なる Binding、dispatch guard の既存 assertion を正本の記録で検証する。

## 試験 node ID の対応

起点と最終版の collection を集合比較。**1525 → 1450（-75）**。
集合上の旧 node 129件、新 node 54件。うち **移設・名称/parameter名変更42件、機能撤去87件（IT1 6 + PostgreSQL 81）、新規12件**。UT の件数は不変。対応先が既存の正本試験の場合、それを新規件数には数えない。

| ファイル | 旧 node の削除・移設・名称変更 | 新 node（集合差） | 理由 |
| --- | ---: | ---: | --- |
| `tests/test_local_classifier_provenance.py` | 0 | 1 | 下表で全 variants を照合。 |
| `tests/test_memory.py` | 3 | 0 | 下表で全 variants を照合。 |
| `tests/test_postgres_batch_reads.py` | 12 | 0 | 下表で全 variants を照合。 |
| `tests/test_postgres_memory_confirmation.py` | 2 | 2 | 下表で全 variants を照合。 |
| `tests/test_postgres_memory_context_privacy.py` | 0 | 23 | 下表で全 variants を照合。 |
| `tests/test_postgres_memory_migration.py` | 75 | 0 | 下表で全 variants を照合。 |
| `tests/test_postgres_memory_recovery.py` | 2 | 0 | 下表で全 variants を照合。 |
| `tests/test_postgres_record_retrieval.py` | 1 | 1 | 下表で全 variants を照合。 |
| `tests/test_postgres_stated_at.py` | 2 | 2 | 下表で全 variants を照合。 |
| `tests/test_postgres_stores.py` | 13 | 6 | 下表で全 variants を照合。 |
| `tests/test_postgres_structured_memory.py` | 4 | 0 | 下表で全 variants を照合。 |
| `tests/test_postgres_turn_deletion.py` | 5 | 1 | 下表で全 variants を照合。 |
| `tests/test_postgres_verbatim_removal.py` | 0 | 12 | 下表で全 variants を照合。 |
| `tests/test_structured_classifier.py` | 0 | 6 | 下表で全 variants を照合。 |
| `tests/test_structured_memory.py` | 10 | 0 | 下表で全 variants を照合。 |

### 削除・移設・名称変更した全 node ID

| 旧 node ID | 新 node / 対応先 | 理由 |
| --- | --- | --- |
| `tests/test_memory.py::test_destination_identity_is_whitelisted_and_secret_free[classifier]` | `tests/test_local_classifier_provenance.py::test_destination_identity_is_whitelisted_and_secret_free` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_memory.py::test_destination_identity_is_whitelisted_and_secret_free[extractor]` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_memory.py::test_extractor_rejects_unmanaged_or_unpinned_profiles` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_postgres_batch_reads.py::test_batch_fetches_only_exact_conversation_revision_pairs[results]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batch_fetches_only_exact_conversation_revision_pairs[valid]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batch_preserves_memory_order_and_source_order_across_turns_and_positions` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batched_eligibility_and_valid_reject_a_changed_source[deleted]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batched_eligibility_and_valid_reject_a_changed_source[epoch]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batched_eligibility_and_valid_reject_a_changed_source[excluded]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batched_eligibility_and_valid_reject_a_changed_source[private]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_batched_eligibility_and_valid_reject_a_changed_source[private_turn]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_distinct_source_pair_count_does_not_add_database_statements` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_empty_batch_preserves_vacuous_validity_and_fetches_no_source_body` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_read_statement_count_is_constant_for_one_ten_and_twenty_memories[results]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_batch_reads.py::test_read_statement_count_is_constant_for_one_ten_and_twenty_memories[valid]` | `tests/test_postgres_record_retrieval.py::test_canonical_batch_statement_count_does_not_grow` / `test_exact_source_pairs_and_source_count_use_constant_queries`（既存） | 旧逐語 results/valid の batching 専用試験を削除。query observer は `postgres_query_support.py` に移設し、正本の batch 検証を保持。 |
| `tests/test_postgres_memory_confirmation.py::test_pending_source_is_not_current_for_memory_commit` | `tests/test_postgres_memory_confirmation.py::test_pending_source_is_rejected_for_record_registration` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_confirmation.py::test_unanswered_source_is_rejected_before_extraction` | `tests/test_postgres_memory_confirmation.py::test_unanswered_source_is_rejected_before_record_registration` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_concurrent_retries_commit_once_and_preserve_canonical_sources` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_denied_query_with_mutation_is_not_optional[classifier_aba]` | `tests/test_postgres_memory_context_privacy.py::test_denied_query_with_mutation_is_not_optional[classifier_aba]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_denied_query_with_mutation_is_not_optional[policy]` | `tests/test_postgres_memory_context_privacy.py::test_denied_query_with_mutation_is_not_optional[policy]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_denied_query_with_mutation_is_not_optional[scope]` | `tests/test_postgres_memory_context_privacy.py::test_denied_query_with_mutation_is_not_optional[scope]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_destination_changes_during_extraction_prevent_commit[classifier]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_destination_changes_during_extraction_prevent_commit[extractor]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_empty_memory_context_retains_dispatch_guard[classifier]` | `tests/test_postgres_memory_context_privacy.py::test_empty_memory_context_retains_dispatch_guard[classifier]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_empty_memory_context_retains_dispatch_guard[policy]` | `tests/test_postgres_memory_context_privacy.py::test_empty_memory_context_retains_dispatch_guard[policy]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_empty_memory_context_retains_dispatch_guard[scope]` | `tests/test_postgres_memory_context_privacy.py::test_empty_memory_context_retains_dispatch_guard[scope]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_extract_restore_archive_and_retry[episode]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extract_restore_archive_and_retry[semantic]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extraction_timeout_cancel_is_retryable[False]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extraction_timeout_cancel_is_retryable[True]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[choices]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[length]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[provider_error]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[reasoning]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[secret]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate[tool]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization[classifier]` | `tests/test_postgres_memory_context_privacy.py::test_failed_memory_context_rechecks_same_prepared_authorization[classifier]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization[owner]` | `tests/test_postgres_memory_context_privacy.py::test_failed_memory_context_rechecks_same_prepared_authorization[owner]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization[policy]` | `tests/test_postgres_memory_context_privacy.py::test_failed_memory_context_rechecks_same_prepared_authorization[policy]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization[scope]` | `tests/test_postgres_memory_context_privacy.py::test_failed_memory_context_rechecks_same_prepared_authorization[scope]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_oldest_job_allows_later_job_and_explicit_retry` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_failed_rebuild_leaves_old_id_invisible_and_can_retry` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check[payload_denied-False]` | `tests/test_postgres_memory_context_privacy.py::test_failed_search_keeps_final_payload_privacy_check[payload_denied-False]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check[payload_denied-True]` | `tests/test_postgres_memory_context_privacy.py::test_failed_search_keeps_final_payload_privacy_check[payload_denied-True]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check[policy-False]` | `tests/test_postgres_memory_context_privacy.py::test_failed_search_keeps_final_payload_privacy_check[policy-False]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check[policy-True]` | `tests/test_postgres_memory_context_privacy.py::test_failed_search_keeps_final_payload_privacy_check[policy-True]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_failed_search_keeps_history_consent_check_after_inference` | `tests/test_postgres_memory_context_privacy.py::test_failed_search_keeps_history_consent_check_after_inference` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send[base_context]` | `tests/test_postgres_memory_context_privacy.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send[base_context]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send[query_classification]` | `tests/test_postgres_memory_context_privacy.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send[query_classification]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_legacy_job_without_destination_is_not_implicitly_upgraded` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_memory_policy_mismatch_rejected_before_old_classifier` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_more_revocations_after_job_creation_never_restore_sources` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_multisource_revocation_erases_body_and_rebuilds_remaining[delete]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_multisource_revocation_erases_body_and_rebuilds_remaining[private]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor[assistant]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor[excluded]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor[private]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor[tool]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[permission-False]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[permission-False]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[permission-True]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[permission-True]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[sensitive-False]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[sensitive-False]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[sensitive-True]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[sensitive-True]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[unavailable-False]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[unavailable-False]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup[unavailable-True]` | `tests/test_postgres_memory_context_privacy.py::test_optional_memory_denial_allows_local_history_without_lookup[unavailable-True]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination[endpoint-classifier]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination[endpoint-extractor]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination[profile-classifier]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination[profile-extractor]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification[classifier]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification[delete]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification[policy]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification[private]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_same_destination_identity_reopen_and_normalized_noop` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_secret_is_rejected_before_classifier_or_extractor` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_secret_provenance_is_rejected_before_persistence` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_stale_rebuild_does_not_send_or_starve_current_work[16]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_stale_rebuild_does_not_send_or_starve_current_work[1]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[not JSON]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version": "memory-v1", "candidates": [{"kind": "inferred_fact", "basis": "explicit_user_statement", "source_indices": [0]}]}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version": "memory-v1", "candidates": [{"kind": "semantic", "basis": "explicit_user_statement", "source_indices": [0, 0]}]}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version": "memory-v1", "candidates": [{"kind": "semantic", "basis": "explicit_user_statement", "source_indices": [99]}]}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version":"memory-v1","candidates":[],"thinking":"Synthetic"}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version":"memory-v1","schema_version":"memory-v1","candidates":[]}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{"schema_version":"memory-v9","candidates":[]}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs[{}]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case0]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case1]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case2]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case3]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case4]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality[case5]` | 撤去 | MemoryService.extract/run/rebuild・逐語抽出/候補/保存/旧 protocol 専用試験を削除。残る検索認可・optional context の23ケースは別ファイルへ移設。 |
| `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically[event_processed]` | 撤去 | 旧逐語 outbox consume と job 作成の原子性試験。消費 API を撤去し、新 API を追加しない。通知・正本撤回の rollback は保持試験で検証。 |
| `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically[job_insert]` | 撤去 | 旧逐語 outbox consume と job 作成の原子性試験。消費 API を撤去し、新 API を追加しない。通知・正本撤回の rollback は保持試験で検証。 |
| `tests/test_postgres_record_retrieval.py::test_canonical_candidates_ignore_legacy_memories_and_reopen` | `tests/test_postgres_record_retrieval.py::test_canonical_candidates_reopen` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_snapshot_and_single_and_batch_evidence` | `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_preserves_source_dates` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence` | `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_and_receipt` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_candidate_mismatch_rolls_back_prior_candidate_and_keeps_job_retryable` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_changed_schema_contract_is_rejected_without_rewriting_data[ALTER TABLE memories ADD COLUMN unexpected text]` | `tests/test_postgres_stores.py::test_changed_schema_contract_is_rejected_without_rewriting_data[ALTER TABLE memory_episodes ADD COLUMN unexpected text]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_changed_schema_contract_is_rejected_without_rewriting_data[ALTER TABLE memories ALTER COLUMN body TYPE varchar]` | `tests/test_postgres_stores.py::test_changed_schema_contract_is_rejected_without_rewriting_data[ALTER TABLE memory_episodes ALTER COLUMN normalized_text TYPE varchar]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_concurrent_memory_retries_share_one_job_and_result` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_failed_attempt_cannot_retire_or_commit_successor` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_memory_provenance_reopen_and_canonical_retry` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_multisource_revocation_purges_body_and_rebuilds_only_original_epochs[delete]` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_multisource_revocation_purges_body_and_rebuilds_only_original_epochs[private]` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_rebase_never_restores_a_revoked_original_source` | `tests/test_memory_record_store_contract.py::test_revocation_dependencies_fact_all_versions_and_non_resurrection` / `test_concurrent_retries_and_fact_cas`（既存） | 逐語 job/commit/rebase/rebuild 契約を撤去。正本の撤回・再活性化拒否・冪等登録の既存試験を保持。 |
| `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes[other0]` | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_records_and_outboxes[other0]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes[other1]` | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_records_and_outboxes[other1]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes[other2]` | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_records_and_outboxes[other2]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes[other3]` | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_records_and_outboxes[other3]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_structured_memory.py::test_structured_approval_change_requires_explicit_retry[contract]` | 撤去 | 逐語 extractor の構造化出力承認/rebuild 専用。分類器の構造化出力試験は保持。 |
| `tests/test_postgres_structured_memory.py::test_structured_approval_change_requires_explicit_retry[legacy]` | 撤去 | 逐語 extractor の構造化出力承認/rebuild 専用。分類器の構造化出力試験は保持。 |
| `tests/test_postgres_structured_memory.py::test_structured_approval_change_requires_explicit_retry[schema]` | 撤去 | 逐語 extractor の構造化出力承認/rebuild 専用。分類器の構造化出力試験は保持。 |
| `tests/test_postgres_structured_memory.py::test_structured_approval_change_requires_explicit_retry[sdk]` | 撤去 | 逐語 extractor の構造化出力承認/rebuild 専用。分類器の構造化出力試験は保持。 |
| `tests/test_postgres_turn_deletion.py::test_later_saved_and_new_user_turns_remain_extractable` | `tests/test_postgres_turn_deletion.py::test_later_saved_and_new_user_turns_allow_record_registration` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_postgres_turn_deletion.py::test_multisource_memory_rebuild_uses_only_remaining_turns` | 撤去 | 逐語の rebuild・抽出中断専用試験を削除（U6）。履歴削除・正本撤回・検索 guard の試験は保持。 |
| `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_extraction` | 撤去 | 逐語の rebuild・抽出中断専用試験を削除（U6）。履歴削除・正本撤回・検索 guard の試験は保持。 |
| `tests/test_postgres_turn_deletion.py::test_rebuild_failure_never_restores_deleted_memory_body` | 撤去 | 逐語の rebuild・抽出中断専用試験を削除（U6）。履歴削除・正本撤回・検索 guard の試験は保持。 |
| `tests/test_postgres_turn_deletion.py::test_rebuild_revalidates_job_after_another_partial_deletion` | 撤去 | 逐語の rebuild・抽出中断専用試験を削除（U6）。履歴削除・正本撤回・検索 guard の試験は保持。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[fenced-classifier]` | `tests/test_structured_classifier.py::test_fixed_schema_over_actual_sdk_and_fail_closed[fenced]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[fenced-extractor]` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[invalid-classifier]` | `tests/test_structured_classifier.py::test_fixed_schema_over_actual_sdk_and_fail_closed[invalid]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[invalid-extractor]` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[unsupported-classifier]` | `tests/test_structured_classifier.py::test_fixed_schema_over_actual_sdk_and_fail_closed[unsupported]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[unsupported-extractor]` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[valid-classifier]` | `tests/test_structured_classifier.py::test_fixed_schema_over_actual_sdk_and_fail_closed[valid]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_structured_memory.py::test_fixed_schema_over_actual_sdk_and_fail_closed[valid-extractor]` | 撤去 | LocalExtractor の初期化・固定出力 schema 専用。分類器側のケースは下表の新 node へ移設。 |
| `tests/test_structured_memory.py::test_public_caller_cannot_supply_provider_output_schema[CompletionInput]` | `tests/test_structured_classifier.py::test_public_caller_cannot_supply_provider_output_schema[CompletionInput]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |
| `tests/test_structured_memory.py::test_public_caller_cannot_supply_provider_output_schema[TurnInput]` | `tests/test_structured_classifier.py::test_public_caller_cannot_supply_provider_output_schema[TurnInput]` | 残る契約を保持。移設または正本の登録/検索を表す名称・parameter名へ変更。 |

### 新規 node ID（12件）

| 新 node ID | 受入範囲 |
| --- | --- |
| `tests/test_postgres_verbatim_removal.py::test_current_schema_rejects_leftover_verbatim_table[memories]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_current_schema_rejects_leftover_verbatim_table[memory_jobs]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_current_schema_rejects_leftover_verbatim_table[memory_sources]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_malformed_v5_is_rejected_before_any_verbatim_drop[ALTER TABLE memories ALTER COLUMN body TYPE varchar]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_malformed_v5_is_rejected_before_any_verbatim_drop[ALTER TABLE memory_sources DROP CONSTRAINT memory_sources_binding_memory_fkey]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_malformed_v5_is_rejected_before_any_verbatim_drop[DROP INDEX memory_source_lookup]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v5_removal_preserves_rows_and_reopens` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v5_removal_rolls_back_every_drop_and_retries[jobs]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v5_removal_rolls_back_every_drop_and_retries[memories]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v5_removal_rolls_back_every_drop_and_retries[sources]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v5_removal_rolls_back_every_drop_and_retries[version]` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |
| `tests/test_postgres_verbatim_removal.py::test_v6_new_schema_has_no_verbatim_relations_and_reopens` | 版5→6削除・保持・rollback・旧版拒否・版6新規/再オープン。 |

### node ID 不変の置換

`test_memory_ranking.py` は旧 Memory を合成 RetrievalCandidate に置き換え `rank_records` を検証する。順位・vector・port metadata の既存 variants を保持。`test_memory_evaluation.py` は結果 object/citation の identity と除外前 embedding を同じ node で保持する。
確認保留/削除の shared contracts、factory、正本撤回試験は旧逐語 assertion を正本の current/retrievable/normalized_text に置換した。node ID の集合だけを根拠に assertion 不変とは扱わない。

## #105 文書同期への引き渡し

本文同期は未実施。利用文書を更新し、歴史的 ADR/証跡は当時の意味を失わないよう必要な置換注記を判断する。

| 文書・箇所 | 残っている記述 / 同期対象 |
| --- | --- |
| `SPEC.md:60,66,166,181` | 現行逐語記憶・削除未実装の状態、実施手順。 |
| `docs/memory.md:9–29,74,111,162,178,251,330` | MemoryStore/LocalExtractor/MemoryService の構成・API、schema v5、逐語/consume 維持。 |
| `docs/postgresql.md:93,199,234` | stores.memory/MemoryService の例、open_storage と旧 MemoryStore の関係、4→5で逐語も保持する現在版説明。 |
| `docs/history-api.md:119` | v1〜4からv5へという最新版説明。 |
| `docs/semantic-postgresql-integration.md:11–20` | MemoryService/stores.memory の起動例。 |
| `docs/memory-evaluation.md:72` | MemoryService/PostgreSQL での検証という記述（U8、本文変更は #105）。 |
| `docs/adr/0008-managed-structured-output.md:12` | LocalExtractor と Extraction の対象。 |
| `docs/adr/0010-in-process-memory-search.md:28,95` | MemoryService への embedding 注入と search（#103で置換注記済み）。 |
| `docs/adr/0011-local-memory-embedding.md:28,55,59` | MemoryService を担い手とする説明（#103で置換注記済み）。 |
| `docs/adr/0012-postgresql-storage.md:19–20` | PostgresMemory / MemoryStore adapter。 |
| `docs/adr/0017-memory-formation-admission.md:136` | MemoryService.extract を残すかという後続境界。 |
| `docs/adr/0015-memory-model-reorganization.md:7,89` / `0016-memory-kinds-and-records.md:21,116` | 当時の逐語形式・削除決定の背景。決定自体は維持し、実施状態との区別を判断。 |
| `docs/adr/0018-memory-retrieval-context.md:5` / `0022-memory-retrieval-from-records.md:14–15,68,79` | #103での切替と書込/削除の後続区分。#104完了注記が必要か判断。 |
| `docs/evidence/2026-10-03-memory.md` / `2026-10-07-memory-record-store.md` / `2026-10-07-schema-version-constant.md` / `2026-10-08-record-retrieval.md` 等 | 旧 MemoryService/PostgresMemory/逐語保持/schema v5 を含む歴史的証跡。当時の結果を上書きせず本証跡を参照して区別。 |

README / CONTEXT に上記識別子・版5・逐語の直接記述は今回の全文検索で検出しなかった。概念整理まで同期完了したという意味ではない。

## 未解決・制約

実装範囲内の未解決 FAIL はなし。保存履歴と正本の論理消去を検証し、WAL/媒体の物理消去は受入にしていない。
形成ができるまで再生成しない期間を許容する（U6）。outbox は保持し、消費機能を追加していない。
実 DB 適用、IT2/ST、品質評価、remote CI、監督レビューは NOT RUN。文書同期は #105、評価再設計は PR #51。
この実装担当は commit のみ。push / PR 作成 / merge を行っていない。
