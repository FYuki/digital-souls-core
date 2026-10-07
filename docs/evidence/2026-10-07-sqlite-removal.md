# SQLite adapter・設定・試験の撤去（Issue #88）

対象: [Issue #88](https://github.com/FYuki/digital-souls-core/issues/88)、Epic #79。
起点: `ca313ec185395433a77b25a7d78cb9a6d2034a94`。作業branch: `feature/88-remove-sqlite`。合成データのみを使用。
固定toolchain: uv 0.8.22、Python 3.12、Node 24.19.0。試験は `TMPDIR=/dev/shm` で実行。
push・PR作成・merge・Issue操作は行っていない。実LLM・実モデル評価・実環境IT2/ST・公開CI・CodeRabbitは **NOT RUN**。

## 変更範囲

`sqlite_history.py`・`sqlite_memory.py`・`memory_sql.py`を削除した。`memory_sql`の参照は削除対象adapterと旧試験に限定され、PostgreSQL adapterからの参照はない。Git管理外保存先、POSIX権限、symlink/hardlink拒否、secure_deleteなどの専用検査もadapterごと撤去した。
`StorageConfig`は必須の`backend: Literal["postgresql"]`と必須の`postgres`だけを持つ。strict・extra=forbid・入力非表示とfactoryの再検証を維持した。PostgreSQL adapterと保存契約は変更していない。設定例は変更せず読込み成功を検証した。
現行接続例・手順をPostgreSQLへ更新した。ADR 0021とADR一覧には完了注記だけを追加し、ADR本文と既存証跡を保持した。SPECは機能単位の状態のみを更新した。
CIにSQLite固有step・環境はなく、workflow変更は不要だった。api-quality / postgres-storage / docs-toolingの名前・常時実行条件は維持した。試験の版番号整理（#82）は変更していない。

## TDD

1. `uv sync --frozen`で78パッケージを導入し、変更前collectionを記録した。
2. 実装変更前に設定拒否・設定schema/例の試験を追加。`pytest tests/test_storage.py -k "retired_and or only_explicit" -q`は **4 FAIL / 3 PASS / 10 deselected**。backend="sqlite"、sqlite_pathあり、およびpostgresqlでsqlite_path=nullが受理される3件と、schemaに余分field・任意postgresが残る1件が意図したRED。
3. factoryをPostgreSQLだけにして同じ対象を含むstorage試験は **16 PASS / 0 FAIL / 0 SKIP**。SQLite設定そのものの3拒否入力も個別実行で **3 PASS**。
4. 継続試験は許可値・field・必須fieldのschema厳密一致と未知backend/field・型暗黙変換拒否を検証する形へ整理した。拒否例の旧backend/fieldを汎用のretired/storage_pathへ置き換え、コード内に撤去済み設定名を残さない。schema一致により旧backend/fieldも許可集合にないことを保証する。
5. 移設直後のimport不足によるcollection ERROR・mypy FAILを修正後、全必須ゲートを実行した。これらの途中失敗は最終PASSへ数えない。

## collectionと件数の照合

`uv run --no-sync pytest --collect-only -q -m ut` / `it1` / `postgres`でパラメタ展開後のケース数を記録した。

| marker | 作業前 | 作業後 | 増減 |
| --- | ---: | ---: | ---: |
| ut | 477 | 462 | -15 |
| it1 | 863 | 473 | -390 |
| postgres | 479 | 526 | +47 |

全collectionは1819→1461件。UTは22件削除・設定契約7件追加で477→462件。IT1は343件削除・47件をPostgreSQLへ移設して863→473件。postgresは既存479件を維持し47件追加して526件。いずれも0件ではない。

## helper・契約関数の移設

変更前に `rg -n "from \.test_|from \. import test_" tests` で全件を走査し、SQLite試験モジュールへの依存を確認した。保存非依存のprovider用test module等へのimportは維持した。

| 元モジュール | 移設先 | 内容 |
| --- | --- | --- |
| test_conversations | conversation_support | SyntheticPolicy、turn、PausedProvider |
| test_privacy | privacy_support | BINDING、assessment、local_profile |
| test_history_stated_at | time_support | FIRST、SECOND |
| test_memory | memory_support | selection |
| test_memory_confirmation | memory_confirmation_contracts | Harness、make_harness、HTTP補助、保存非依存の契約関数 |
| test_turn_deletion | turn_deletion_contracts | Storage、通知Protocol、HTTP補助、全共有契約関数 |

移設した59個の関数/classのAST（decorator・本体のassertionを含む）は元定義と完全一致。既存PostgreSQLモジュールの278個の関数/class/代入も起点とAST完全一致。変更はimport先のみで、既存479件の検証内容は変えていない。
`test_postgres_turn_deletion`と`test_postgres_memory_confirmation`は新しいcontracts moduleから同じ関数を公開し、同じPostgreSQL fixtureで実行する。

## 削除したUT/IT1の個別対応

[履歴対応表](2026-10-07-history-test-migration.md)と[記憶対応表](2026-10-07-memory-test-migration.md)の全ケースと照合した。下表の件数は移設を除く純削除。関数ごとのパラメタ全ケースが対象。SQLite固有を除き、対応先の検証を最終postgresゲートで実行した。

| 元ファイル・関数 | UT削除 | IT1削除 | PostgreSQL側の対応試験／移植しない理由 |
| --- | ---: | ---: | --- |
| `tests/test_conversation_controls.py::test_archive_only_changes_listing_and_preserves_memory_source` | 0 | 1 | `tests/test_postgres_conversation_controls.py::test_archive_only_changes_listing_and_preserves_memory_source`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_delete_atomically_notifies_and_invalidates_sources` | 0 | 1 | `tests/test_postgres_conversation_controls.py::test_delete_atomically_notifies_and_invalidates_sources`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_delete_event_and_history_deletion_rollback_together` | 0 | 1 | `tests/test_postgres_stores.py::test_failed_revocation_rolls_back_history_memory_and_outboxes_together` |
| `tests/test_conversation_controls.py::test_excluded_history_cannot_reenter_via_later_assistant` | 0 | 2 | `tests/test_postgres_conversation_controls.py::test_excluded_history_cannot_reenter_via_later_assistant`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_explicit_excluded_utterance_preserves_history_and_retry` | 0 | 1 | `tests/test_postgres_conversation_controls.py::test_explicit_excluded_utterance_preserves_history_and_retry`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_private_change_conflicts_with_inflight_inference` | 0 | 1 | `tests/test_postgres_conversation_controls.py::test_private_change_conflicts_with_inflight_inference`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_thread_private_then_public_does_not_retroactively_admit_private_turn` | 0 | 1 | `tests/test_postgres_conversation_controls.py::test_thread_private_then_public_does_not_retroactively_admit_private_turn`（新規、全ケース移植） |
| `tests/test_conversation_controls.py::test_v1_upgrade_preserves_history_and_receipt` | 0 | 3 | SQLite固有user_version/ALTER移行3ケースは移植しない。PostgreSQL保持・中断再試行は `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence` / `tests/test_postgres_stated_at.py::test_v1_migration_interruption_rolls_back_and_retries` で検証 |
| `tests/test_conversations.py::test_concurrent_retry_reauthorizes_actual_winner_receipt` | 0 | 2 | `tests/test_postgres_conversations.py::test_concurrent_retry_reauthorizes_actual_winner_receipt`（新規、全ケース移植） |
| `tests/test_conversations.py::test_delivery_failure_after_commit_keeps_retry_receipt` | 0 | 2 | `tests/test_postgres_conversations.py::test_delivery_failure_after_commit_keeps_retry_receipt`（新規、全ケース移植） |
| `tests/test_conversations.py::test_export_revocation_during_context_lookup` | 0 | 2 | `tests/test_postgres_conversations.py::test_export_revocation_during_context_lookup`（新規、全ケース移植） |
| `tests/test_conversations.py::test_failed_stream_never_persists` | 0 | 7 | `tests/test_postgres_conversations.py::test_failed_stream_never_persists`（新規、全ケース移植） |
| `tests/test_conversations.py::test_fragmented_stream_tool_arguments_and_multiple_results` | 0 | 1 | `tests/test_postgres_conversations.py::test_fragmented_stream_tool_arguments_and_multiple_results`（新規、全ケース移植） |
| `tests/test_conversations.py::test_http_disconnect_discards_uncommitted_turn` | 0 | 2 | `tests/test_postgres_conversations.py::test_http_disconnect_discards_uncommitted_turn`（新規、全ケース移植） |
| `tests/test_conversations.py::test_http_opt_in_crud_stream_and_reject_scope` | 0 | 1 | `tests/test_postgres_conversations.py::test_http_opt_in_crud_stream_and_reject_scope`（新規、全ケース移植） |
| `tests/test_conversations.py::test_inflight_boundaries` | 0 | 8 | `tests/test_postgres_conversations.py::test_inflight_boundaries`（新規、全ケース移植） |
| `tests/test_conversations.py::test_policy_fail_closed_on_each_boundary_and_delete_after_revocation` | 0 | 1 | `tests/test_postgres_conversations.py::test_policy_fail_closed_on_each_boundary_and_delete_after_revocation`（新規、全ケース移植） |
| `tests/test_conversations.py::test_reasoning_fields_are_not_saved` | 0 | 1 | `tests/test_postgres_conversations.py::test_reasoning_fields_are_not_saved`（新規、全ケース移植） |
| `tests/test_conversations.py::test_restore_retry_and_new_turn_context` | 0 | 1 | `tests/test_postgres_conversations.py::test_restore_retry_and_new_turn_context`（新規、全ケース移植） |
| `tests/test_conversations.py::test_same_tick_disconnect_and_provider_completion` | 0 | 4 | `tests/test_postgres_conversations.py::test_same_tick_disconnect_and_provider_completion`（新規、全ケース移植） |
| `tests/test_conversations.py::test_sdk_profile_defaults_preserve_pre_llamacpp_receipt` | 0 | 1 | `tests/test_postgres_conversations.py::test_sdk_profile_defaults_preserve_pre_llamacpp_receipt`（新規、全ケース移植） |
| `tests/test_conversations.py::test_size_role_and_invalid_output_rejections` | 0 | 1 | `tests/test_postgres_conversations.py::test_size_role_and_invalid_output_rejections`（新規、全ケース移植） |
| `tests/test_conversations.py::test_tool_roundtrip` | 0 | 2 | `tests/test_postgres_conversations.py::test_tool_roundtrip`（新規、全ケース移植） |
| `tests/test_history.py::test_every_store_operation_is_scoped` | 3 | 0 | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes` |
| `tests/test_history.py::test_first_schema_creation_recovers_after_process_exit` | 4 | 0 | `tests/test_postgres_history_initialization.py::test_first_schema_creation_recovers_after_process_exit` |
| `tests/test_history.py::test_order_reopen_idempotency_conflict_and_delete` | 1 | 0 | `tests/test_postgres_stores.py::test_history_order_retry_cas_reopen_and_delete` / `tests/test_postgres_history_initialization.py::test_deleted_conversation_cannot_be_resurrected_by_late_append` |
| `tests/test_history.py::test_secure_defaults_and_reject_unsafe_storage` | 1 | 0 | 移植しない：SQLite固有のファイル保存先・POSIX権限・hardlink/symlink・Git管理下制約。PostgreSQL接続境界は既存test_postgres_config.pyで検証 |
| `tests/test_history.py::test_unknown_schema_is_not_overwritten` | 1 | 0 | `tests/test_postgres_stores.py::test_unknown_schema_version_is_preserved_and_rejected` |
| `tests/test_history.py::test_unknown_unversioned_schema_still_fails_closed` | 1 | 0 | `tests/test_postgres_history_initialization.py::test_unknown_unversioned_schema_is_preserved_and_rejected` |
| `tests/test_history_llamacpp.py::test_history_with_production_local_adapter` | 0 | 6 | `tests/test_postgres_history_llamacpp.py::test_history_with_production_local_adapter`（新規、全ケース移植） |
| `tests/test_history_stated_at.py::test_clock_is_sampled_per_turn_and_restored_for_every_message` | 1 | 0 | `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_snapshot_and_single_and_batch_evidence` |
| `tests/test_history_stated_at.py::test_default_clock_records_current_utc_at_append` | 1 | 0 | `tests/test_postgres_stated_at.py::test_new_schema_is_v5_and_default_clock_is_current_utc` |
| `tests/test_history_stated_at.py::test_evidence_uses_saved_time_without_changing_source_or_job_identity` | 1 | 0 | `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_snapshot_and_single_and_batch_evidence` |
| `tests/test_history_stated_at.py::test_http_completion_get_and_patch_preserve_turn_times` | 0 | 2 | `tests/test_postgres_history_api.py::test_http_completion_get_and_patch_preserve_turn_times`（新規、全ケース移植） |
| `tests/test_history_stated_at.py::test_legacy_http_null_and_service_retry_do_not_infer_again` | 0 | 1 | `tests/test_postgres_history_api.py::test_legacy_http_null_and_service_retry_do_not_infer_again`（新規、全ケース移植） |
| `tests/test_history_stated_at.py::test_legacy_migration_preserves_null_receipt_fingerprint_and_evidence` | 3 | 0 | SQLite user_version 1/2/3は移植しない。保持契約は `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence` で検証 |
| `tests/test_history_stated_at.py::test_naive_clock_rejects_without_turn_or_revision_and_allows_retry` | 1 | 0 | `tests/test_postgres_stated_at.py::test_naive_clock_rolls_back_and_valid_retry_saves_timestamp` |
| `tests/test_history_stated_at.py::test_v4_migration_process_exit_rolls_back_then_retries` | 2 | 0 | SQLite固有user_version 3→4とtrace_callbackによる終了は移植しない。PostgreSQL列/版登録のrollbackは `tests/test_postgres_stated_at.py::test_v1_migration_interruption_rolls_back_and_retries`、実プロセス終了は新規initialization試験で検証 |
| `tests/test_memory.py::test_concurrent_retries_commit_once_and_preserve_canonical_sources` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_concurrent_retries_commit_once_and_preserve_canonical_sources` |
| `tests/test_memory.py::test_context_opt_in_stateless_compatibility_and_dispatch_guard` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_context_opt_in_stateless_compatibility_and_dispatch_guard` |
| `tests/test_memory.py::test_context_provenance_survives_final_classifier_await` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_context_provenance_survives_final_classifier_await` |
| `tests/test_memory.py::test_denied_query_with_mutation_is_not_optional` | 0 | 3 | 新規: `tests/test_postgres_memory_migration.py::test_denied_query_with_mutation_is_not_optional` |
| `tests/test_memory.py::test_destination_changes_during_extraction_prevent_commit` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_destination_changes_during_extraction_prevent_commit` |
| `tests/test_memory.py::test_direct_storage_search_error_still_propagates` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_direct_storage_search_error_still_propagates` |
| `tests/test_memory.py::test_empty_memory_context_retains_dispatch_guard` | 0 | 3 | 新規: `tests/test_postgres_memory_migration.py::test_empty_memory_context_retains_dispatch_guard` |
| `tests/test_memory.py::test_extract_restore_search_archive_and_retry` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_extract_restore_search_archive_and_retry` |
| `tests/test_memory.py::test_extraction_timeout_cancel_is_retryable` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_extraction_timeout_cancel_is_retryable` |
| `tests/test_memory.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate` | 0 | 6 | 新規: `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate` |
| `tests/test_memory.py::test_failed_memory_context_rechecks_same_prepared_authorization` | 0 | 4 | 新規: `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization` |
| `tests/test_memory.py::test_failed_oldest_job_allows_later_job_and_explicit_retry` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_failed_oldest_job_allows_later_job_and_explicit_retry` |
| `tests/test_memory.py::test_failed_rebuild_leaves_old_id_invisible_and_can_retry` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_failed_rebuild_leaves_old_id_invisible_and_can_retry` |
| `tests/test_memory.py::test_failed_search_keeps_final_payload_privacy_check` | 0 | 4 | 新規: `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check` |
| `tests/test_memory.py::test_failed_search_keeps_history_consent_check_after_inference` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_failed_search_keeps_history_consent_check_after_inference` |
| `tests/test_memory.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send` |
| `tests/test_memory.py::test_late_failed_attempt_cannot_retire_or_commit_explicit_retry` | 0 | 1 | 既存: `tests/test_postgres_stores.py::test_failed_attempt_cannot_retire_or_commit_successor` |
| `tests/test_memory.py::test_legacy_job_without_destination_is_not_implicitly_upgraded` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_legacy_job_without_destination_is_not_implicitly_upgraded` |
| `tests/test_memory.py::test_memory_policy_mismatch_rejected_before_old_classifier` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_memory_policy_mismatch_rejected_before_old_classifier` |
| `tests/test_memory.py::test_memory_scope_never_crosses_sources_results_events` | 0 | 4 | 既存: `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes` |
| `tests/test_memory.py::test_memory_search_errors_allow_memoryless_conversation` | 0 | 10 | 新規: `tests/test_postgres_memory_migration.py::test_memory_search_errors_allow_memoryless_conversation` |
| `tests/test_memory.py::test_mixed_fact_and_instruction_is_framed_as_historical_data` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_mixed_fact_and_instruction_is_framed_as_historical_data` |
| `tests/test_memory.py::test_more_revocations_after_job_creation_never_restore_sources` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_more_revocations_after_job_creation_never_restore_sources` |
| `tests/test_memory.py::test_multisource_revocation_erases_body_and_rebuilds_remaining` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_multisource_revocation_erases_body_and_rebuilds_remaining` |
| `tests/test_memory.py::test_non_user_or_ineligible_sources_never_reach_extractor` | 0 | 4 | 新規: `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor` |
| `tests/test_memory.py::test_optional_memory_denial_allows_local_history_without_lookup` | 0 | 6 | 新規: `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup` |
| `tests/test_memory.py::test_rebuild_approval_binds_managed_destination` | 0 | 4 | 新規: `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination` |
| `tests/test_memory.py::test_revocation_outbox_crash_replays_atomically` | 0 | 3 | 既存: `tests/test_postgres_stores.py::test_failed_revocation_rolls_back_history_memory_and_outboxes_together` のaction=delete / 新規: `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically` のstage=job_insert / 新規: `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically` のstage=event_processed |
| `tests/test_memory.py::test_revoke_during_extractor_await_no_commit_or_next_classification` | 0 | 4 | 新規: `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification` |
| `tests/test_memory.py::test_same_destination_identity_reopen_and_normalized_noop` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_same_destination_identity_reopen_and_normalized_noop` |
| `tests/test_memory.py::test_search_is_bounded` | 0 | 4 | 既存: `tests/test_postgres_stores.py::test_memory_query_bounds` |
| `tests/test_memory.py::test_secret_is_rejected_before_classifier_or_extractor` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_secret_is_rejected_before_classifier_or_extractor` |
| `tests/test_memory.py::test_secret_provenance_is_rejected_before_persistence` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_secret_provenance_is_rejected_before_persistence` |
| `tests/test_memory.py::test_stale_rebuild_does_not_send_or_starve_current_work` | 0 | 2 | 新規: `tests/test_postgres_memory_migration.py::test_stale_rebuild_does_not_send_or_starve_current_work` |
| `tests/test_memory.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs` | 0 | 9 | 新規: `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs` |
| `tests/test_memory.py::test_synthetic_protocol_corpus_not_model_quality` | 0 | 6 | 新規: `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality` |
| `tests/test_memory.py::test_unexpected_memory_storage_error_propagates` | 0 | 1 | 新規: `tests/test_postgres_memory_migration.py::test_unexpected_memory_storage_error_propagates` |
| `tests/test_memory.py::test_v2_memory_migration_recovers_without_losing_history` | 0 | 5 | 移植しない: SQLiteのv2 history-only schemaへの5つのDDL/PRAGMA中断点。PostgreSQL v1には既に記憶表があり、このschema段階・SQLite subprocess trace callbackは存在しない。一般の原子性は下記outbox/既存PostgreSQL rollback試験で保持。 |
| `tests/test_memory_confirmation.py::test_accept_erases_existing_memory_and_never_restores_accepted_source` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_accept_erases_existing_memory_and_never_restores_accepted_source` |
| `tests/test_memory_confirmation.py::test_assistant_refusal_quotes_and_history_do_not_hold_new_user` | 0 | 12 | 既存: `tests/test_postgres_memory_confirmation.py::test_assistant_refusal_quotes_and_history_do_not_hold_new_user` |
| `tests/test_memory_confirmation.py::test_confirmation_cannot_change_another_binding` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_cannot_change_another_binding` |
| `tests/test_memory_confirmation.py::test_confirmation_invalidates_inflight_completion` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_invalidates_inflight_completion` |
| `tests/test_memory_confirmation.py::test_confirmation_obeys_history_policy` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_obeys_history_policy` |
| `tests/test_memory_confirmation.py::test_decline_does_not_disable_private_mode` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_decline_does_not_disable_private_mode` |
| `tests/test_memory_confirmation.py::test_decline_releases_only_target_and_preserves_explicit_exclusion` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_decline_releases_only_target_and_preserves_explicit_exclusion` |
| `tests/test_memory_confirmation.py::test_pending_confirmation_and_receipt_survive_sqlite_restart` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_pending_confirmation_and_receipt_survive_postgres_restart` |
| `tests/test_memory_confirmation.py::test_pending_source_is_not_current_for_memory_commit` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_pending_source_is_not_current_for_memory_commit` |
| `tests/test_memory_confirmation.py::test_refusal_signal_guides_user_selected_turn_and_whole_history_deletion` | 0 | 2 | 新規: `tests/test_postgres_memory_confirmation_migration.py::test_refusal_signal_guides_user_selected_turn_and_whole_history_deletion` |
| `tests/test_memory_confirmation.py::test_refusal_signal_identifies_each_user_source_without_content` | 0 | 4 | 既存: `tests/test_postgres_memory_confirmation.py::test_refusal_signal_identifies_each_user_source_without_content` |
| `tests/test_memory_confirmation.py::test_resolved_confirmation_retry_keeps_receipt_dates_and_does_not_rehold` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_resolved_confirmation_retry_keeps_receipt_dates_and_does_not_rehold` |
| `tests/test_memory_confirmation.py::test_sqlite_accept_rollback_preserves_memory_and_allows_retry` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_postgres_accept_rollback_preserves_memory_and_allows_retry` |
| `tests/test_memory_confirmation.py::test_sqlite_v4_migration_keeps_old_dates_receipts_and_does_not_scan_history` | 0 | 2 | 既存: `tests/test_postgres_memory_confirmation.py::test_postgres_v2_migration_keeps_old_dates_receipts_and_does_not_scan_history` |
| `tests/test_memory_confirmation.py::test_stale_and_repeated_confirmation_leave_state_unchanged` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_stale_and_repeated_confirmation_leave_state_unchanged` |
| `tests/test_memory_confirmation.py::test_tool_refusal_text_does_not_create_confirmation` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_tool_refusal_text_does_not_create_confirmation` |
| `tests/test_memory_confirmation.py::test_unanswered_source_is_rejected_before_extraction` | 0 | 1 | 既存: `tests/test_postgres_memory_confirmation.py::test_unanswered_source_is_rejected_before_extraction` |
| `tests/test_memory_context_refs.py::test_context_references_preserve_shared_source_relationships` | 0 | 1 | 新規: `tests/test_postgres_memory_context_refs.py::test_context_references_preserve_shared_source_relationships` |
| `tests/test_memory_context_refs.py::test_generated_identifier_collision_preserves_content_policy_and_guard` | 0 | 8 | 新規: `tests/test_postgres_memory_context_refs.py::test_generated_identifier_collision_preserves_content_policy_and_guard` |
| `tests/test_privacy.py::test_actual_payload_injection_blocked` | 0 | 3 | `tests/test_postgres_history_privacy.py::test_actual_payload_injection_blocked`（新規、全ケース移植） |
| `tests/test_privacy.py::test_history_policy_cannot_be_disconnected` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_history_policy_cannot_be_disconnected`（新規、全ケース移植） |
| `tests/test_privacy.py::test_local_external_memory_permissions_and_sensitive_history` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_local_external_memory_permissions_and_sensitive_history`（新規、全ケース移植） |
| `tests/test_privacy.py::test_natural_language_does_not_change_operation_scope` | 0 | 4 | `tests/test_postgres_history_privacy.py::test_natural_language_does_not_change_operation_scope`（新規、全ケース移植） |
| `tests/test_privacy.py::test_natural_language_without_exclusion_holds_source_for_confirmation` | 0 | 4 | `tests/test_postgres_history_privacy.py::test_natural_language_without_exclusion_holds_source_for_confirmation`（新規、全ケース移植） |
| `tests/test_privacy.py::test_policy_replacement_prevents_context_lookup` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_policy_replacement_prevents_context_lookup`（新規、全ケース移植） |
| `tests/test_privacy.py::test_retry_and_output_recheck_current_grants` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_retry_and_output_recheck_current_grants`（新規、全ケース移植） |
| `tests/test_privacy.py::test_revocation_during_classifier_wait` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_revocation_during_classifier_wait`（新規、全ケース移植） |
| `tests/test_privacy.py::test_secret_never_reaches_classifier_or_history` | 0 | 5 | `tests/test_postgres_history_privacy.py::test_secret_never_reaches_classifier_or_history`（新規、全ケース移植） |
| `tests/test_privacy.py::test_stream_secret_split_never_saved` | 0 | 1 | `tests/test_postgres_history_privacy.py::test_stream_secret_split_never_saved`（新規、全ケース移植） |
| `tests/test_semantic_memory.py::test_broken_embedding_metadata_is_content_free` | 0 | 1 | 新規: `tests/test_postgres_semantic_migration.py::test_broken_embedding_metadata_is_content_free` |
| `tests/test_semantic_memory.py::test_changes_during_await_fail_closed` | 0 | 18 | 新規: `tests/test_postgres_semantic_migration.py::test_changes_during_await_fail_closed` / 既存: `tests/test_postgres_semantic_memory.py::test_postgres_search_rechecks_storage_and_embedding_generation_after_await`（change=store/generation/space） |
| `tests/test_semantic_memory.py::test_conversation_cancel_during_embedding_propagates_without_append` | 0 | 1 | 新規: `tests/test_postgres_semantic_migration.py::test_conversation_cancel_during_embedding_propagates_without_append` |
| `tests/test_semantic_memory.py::test_denied_content_and_oversize_scope_never_reach_embedding` | 0 | 5 | 新規: `tests/test_postgres_semantic_migration.py::test_denied_content_and_oversize_scope_never_reach_embedding` |
| `tests/test_semantic_memory.py::test_embedding_failure_allows_memoryless_conversation` | 0 | 8 | 新規: `tests/test_postgres_semantic_migration.py::test_embedding_failure_allows_memoryless_conversation` |
| `tests/test_semantic_memory.py::test_embedding_failure_is_bounded_content_free_and_never_optional` | 0 | 4 | 新規: `tests/test_postgres_semantic_migration.py::test_embedding_failure_is_bounded_content_free_and_never_optional` |
| `tests/test_semantic_memory.py::test_equal_relevance_prefers_latest_user_mention_over_newer_memory` | 0 | 1 | 既存: `tests/test_postgres_semantic_memory.py::test_postgres_equal_relevance_prefers_latest_user_mention` |
| `tests/test_semantic_memory.py::test_ineligible_history_is_never_promoted_by_semantic_search` | 0 | 2 | 新規: `tests/test_postgres_semantic_migration.py::test_ineligible_history_is_never_promoted_by_semantic_search` |
| `tests/test_semantic_memory.py::test_invalid_search_rejected_before_classifier_or_embedding` | 0 | 5 | 新規: `tests/test_postgres_semantic_migration.py::test_invalid_search_rejected_before_classifier_or_embedding` |
| `tests/test_semantic_memory.py::test_nonselected_source_revoked_during_result_authorization_rejects_search` | 0 | 1 | 新規: `tests/test_postgres_semantic_migration.py::test_nonselected_source_revoked_during_result_authorization_rejects_search` |
| `tests/test_semantic_memory.py::test_opt_in_synonym_ranking_preserves_memory_and_source_provenance` | 0 | 1 | 新規: `tests/test_postgres_semantic_migration.py::test_opt_in_synonym_ranking_preserves_memory_and_source_provenance` |
| `tests/test_semantic_memory.py::test_revocation_and_rebuild_never_reembed_withdrawn_source` | 0 | 2 | 新規: `tests/test_postgres_semantic_migration.py::test_revocation_and_rebuild_never_reembed_withdrawn_source` |
| `tests/test_semantic_memory.py::test_semantic_candidates_never_cross_any_binding_axis` | 0 | 4 | 既存: `tests/test_postgres_semantic_memory.py::test_semantic_search_never_embeds_another_postgres_scope` |
| `tests/test_semantic_memory.py::test_semantic_context_retains_dispatch_guard_and_stateless_compatibility` | 0 | 6 | 新規: `tests/test_postgres_semantic_migration.py::test_semantic_context_retains_dispatch_guard_and_stateless_compatibility` |
| `tests/test_semantic_memory.py::test_semantic_revocation_during_dispatch_classification_never_calls_provider` | 0 | 2 | 既存: `tests/test_postgres_semantic_memory.py::test_revocation_after_context_assembly_prevents_model_dispatch` |
| `tests/test_semantic_memory.py::test_semantic_search_returns_at_most_poc_max_retrieved` | 0 | 1 | 新規: `tests/test_postgres_semantic_migration.py::test_semantic_search_returns_at_most_poc_max_retrieved` |
| `tests/test_storage.py::test_sqlite_stores_share_explicit_database` | 1 | 0 | `tests/test_postgres_history_initialization.py::test_factory_shares_explicit_database_without_extracting` |
| `tests/test_turn_deletion.py::test_deleted_request_retry_is_rejected_after_restart` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_deleted_request_retry_is_rejected_after_restart`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_deleted_tail_revision_is_never_reused` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_deleted_tail_revision_is_never_reused`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_deletion_scopes_preserve_only_untargeted_history_and_memory` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_deletion_scopes_preserve_only_untargeted_history_and_memory`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_failed_delete_rolls_back_revision_history_memory_and_allows_retry` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_failed_delete_rolls_back_revision_history_memory_and_allows_retry`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_invalid_deletion_input_is_rejected_without_changes` | 0 | 5 | `tests/test_postgres_turn_deletion.py::test_invalid_deletion_input_is_rejected_without_changes`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_invalid_deletion_leaves_all_state_unchanged` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_invalid_deletion_leaves_all_state_unchanged`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_later_saved_and_new_user_turns_remain_extractable` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_later_saved_and_new_user_turns_remain_extractable`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_multiple_calls_and_results_are_deleted_together` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_multiple_calls_and_results_are_deleted_together`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_multisource_memory_rebuild_uses_only_remaining_turns` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_multisource_memory_rebuild_uses_only_remaining_turns`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_natural_language_does_not_delete_history` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_natural_language_does_not_delete_history`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_cannot_change_another_binding` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_cannot_change_another_binding`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_does_not_admit_retained_private_or_excluded_source` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_does_not_admit_retained_private_or_excluded_source`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_invalidates_same_prepared_memory_context` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_invalidates_same_prepared_memory_context`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_rejects_same_inflight_completion` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_completion`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_rejects_same_inflight_extraction` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_extraction`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_rejects_same_inflight_http_completion` | 0 | 2 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_http_completion`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_deletion_remains_available_after_consent_revocation` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_remains_available_after_consent_revocation`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_partial_notification_is_durable_scoped_and_contains_only_identifiers` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_partial_notification_is_durable_scoped_and_contains_only_identifiers`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_rebuild_failure_never_restores_deleted_memory_body` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_rebuild_failure_never_restores_deleted_memory_body`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_rebuild_revalidates_job_after_another_partial_deletion` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_rebuild_revalidates_job_after_another_partial_deletion`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_remaining_dates_confirmation_states_and_receipts_survive_restart` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_remaining_dates_confirmation_states_and_receipts_survive_restart`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_repeated_partial_deletion_is_rejected_without_second_revision_change` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_repeated_partial_deletion_is_rejected_without_second_revision_change`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_retained_accepted_confirmation_stays_ineligible_after_partial_delete` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_retained_accepted_confirmation_stays_ineligible_after_partial_delete`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_same_tool_name_with_different_ids_does_not_join_independent_turns` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_same_tool_name_with_different_ids_does_not_join_independent_turns`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_sqlite_partial_deletion_physically_erases_source_and_derived_text` | 0 | 1 | 移植しない：SQLite固有のsecure_delete/物理ファイル消去。PostgreSQLは論理的取得停止・本文NULL化のみを保証しWAL/媒体の物理消去を保証しない |
| `tests/test_turn_deletion.py::test_tombstone_keeps_request_identifier_without_content_or_fingerprint` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_tombstone_keeps_request_identifier_without_content_or_fingerprint`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_tool_call_result_chain_expands_deletion_in_both_directions` | 0 | 4 | `tests/test_postgres_turn_deletion.py::test_tool_call_result_chain_expands_deletion_in_both_directions`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_tool_identifiers_in_content_do_not_expand_deletion` | 0 | 6 | `tests/test_postgres_turn_deletion.py::test_tool_identifiers_in_content_do_not_expand_deletion`（既存、全ケース同一関数） |
| `tests/test_turn_deletion.py::test_whole_conversation_deletion_preserves_existing_notification_contract` | 0 | 1 | `tests/test_postgres_turn_deletion.py::test_whole_conversation_deletion_preserves_existing_notification_contract`（既存、全ケース同一関数） |
| `tests/test_turn_deletion_migration.py::test_v5_migration_interruption_rolls_back_and_allows_retry` | 1 | 0 | SQLite user_version 5→6は移植しない。保持/rollback/再試行は既存 `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_interruption_rolls_back_and_allows_retry` が検証 |
| `tests/test_turn_deletion_migration.py::test_v5_migration_preserves_stored_time_confirmation_and_receipt` | 0 | 6 | SQLite user_version 5→6は移植しない。NULL/日時×3確認状態の6ケースは既存 `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_preserves_stored_time_confirmation_and_receipt` が同じ契約を検証 |
| **計** | **22** | **343** | |

## 対応表外の間接依存47件（削除せず移設）

helper経由でSQLiteを構成する4ファイルを検出した。対応表外のため試験を削除せず、保存依存ケースを同名関数・parametrizeのまま新しいPostgreSQLモジュールへ移した。保存非依存ケースは既存IT1に保持する。
数値privacyのDBファイルbyte検査のみ、#86・#87と同じく専用schemaの全表の論理行に文字列がない検査へ置き換えた。PostgreSQLの旧tuple・WAL・backup・物理媒体の消去は保証しない。それ以外のassertionは保持した。
保存非依存のhistory_limits `_stream`試験は、storeを接続せず実Conversationsと合成providerで実行し、保存操作を行わない。fake保存adapterは追加していない。

| 元ファイル・関数 | IT1から移設 | 対応先 |
| --- | ---: | --- |
| `tests/test_history_limits.py::test_byte_overflow_closes_stream_without_history` | 5 | `tests/test_postgres_history_limits.py::test_byte_overflow_closes_stream_without_history` |
| `tests/test_history_limits.py::test_combined_input_message_limit_is_http_413` | 1 | `tests/test_postgres_history_limits.py::test_combined_input_message_limit_is_http_413` |
| `tests/test_history_limits.py::test_final_stored_history_exact_byte_limit` | 2 | `tests/test_postgres_history_limits.py::test_final_stored_history_exact_byte_limit` |
| `tests/test_history_limits.py::test_input_at_limit_accepts_response` | 8 | `tests/test_postgres_history_limits.py::test_input_at_limit_accepts_response` |
| `tests/test_local_embedding_memory.py::test_endpoint_change_during_candidate_authorization_never_dispatches` | 1 | `tests/test_postgres_local_embedding_memory.py::test_endpoint_change_during_candidate_authorization_never_dispatches` |
| `tests/test_local_embedding_memory.py::test_sdk_await_rechecks_sources_and_deployment_configuration` | 4 | `tests/test_postgres_local_embedding_memory.py::test_sdk_await_rechecks_sources_and_deployment_configuration` |
| `tests/test_local_embedding_memory.py::test_sdk_receives_only_current_authorized_evidence` | 1 | `tests/test_postgres_local_embedding_memory.py::test_sdk_receives_only_current_authorized_evidence` |
| `tests/test_numeric_privacy.py::test_decimal_encoded_value_blocked_before_send` | 2 | `tests/test_postgres_numeric_privacy.py::test_decimal_encoded_value_blocked_before_send` |
| `tests/test_numeric_privacy.py::test_encoded_json_rejected_before_classifier_and_provider` | 2 | `tests/test_postgres_numeric_privacy.py::test_encoded_json_rejected_before_classifier_and_provider` |
| `tests/test_numeric_privacy.py::test_http_numeric_input_blocks_provider_and_database` | 4 | `tests/test_postgres_numeric_privacy.py::test_http_numeric_input_blocks_provider_and_database` |
| `tests/test_numeric_privacy.py::test_numeric_history_boundaries` | 10 | `tests/test_postgres_numeric_privacy.py::test_numeric_history_boundaries` |
| `tests/test_numeric_privacy.py::test_numeric_tool_enum_rejected_before_send` | 3 | `tests/test_postgres_numeric_privacy.py::test_numeric_tool_enum_rejected_before_send` |
| `tests/test_structured_memory.py::test_structured_approval_change_requires_explicit_retry` | 4 | `tests/test_postgres_structured_memory.py::test_structured_approval_change_requires_explicit_retry` |
| **計** | **47** | |

## 品質ゲート

FAIL・SKIP・NOT RUNはPASSへ含めない。最終実行は全て0 FAIL・0 SKIP。既存Starlette/AnyIO・Pydanticの非失敗警告を含む。

| コマンド | 結果 | 件数・範囲 |
| --- | --- | --- |
| `uv sync --frozen` | PASS | lock固定、初回78パッケージ導入 |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS | Python 102ファイル、0 errors |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS | 102ファイル |
| `uv run --no-sync mypy` | PASS | 102ファイル、0 issues |
| `uv run --no-sync pytest -m ut -q` | PASS | 462件、0 FAIL、0 SKIP |
| `uv run --no-sync pytest -m it1 -q` | PASS | 473件、0 FAIL、0 SKIP |
| `uv build --no-build-isolation` | PASS | sdist・wheelの2成果物 |
| `bash tools/test-postgres.sh` | PASS | 526件、0 FAIL、0 SKIP |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 27件、0 FAIL、0 SKIP/TODO/cancel |
| `node tools/check-docs.mjs` | PASS | 追跡text・Markdown参照・JSONの1ゲート |
| `git diff --check` | PASS | 差分の1ゲート（stagedも照合） |

## 残存参照の全件分類

`git grep -in sqlite` の一致行をファイル・行番号ごとに分類する。製品コード・試験・有効な設定・CIの一致は0件。現行文書は撤去済みを説明する4行だけ。既存証跡とADR本文は履歴として維持し、本証跡は撤去の変更記録として分類する。

| ファイル | 一致行番号（全件） | 分類 |
| --- | --- | --- |
| `CONTRIBUTING.md` | 124 | 撤去済みの最小説明 |
| `README.md` | 60 | 撤去済みの最小説明 |
| `SPEC.md` | 23 | 撤去済みの最小説明 |
| `docs/adr/0004-conversation-history.md` | 17, 22, 24, 47, 62, 83 | ADRの決定履歴・完了注記 |
| `docs/adr/0005-privacy-boundaries.md` | 33 | ADRの決定履歴・完了注記 |
| `docs/adr/0006-conversation-memory-controls.md` | 38, 44 | ADRの決定履歴・完了注記 |
| `docs/adr/0007-memory-provenance-and-revocation.md` | 39, 90, 111, 139 | ADRの決定履歴・完了注記 |
| `docs/adr/0010-in-process-memory-search.md` | 11, 19, 57 | ADRの決定履歴・完了注記 |
| `docs/adr/0011-local-memory-embedding.md` | 65 | ADRの決定履歴・完了注記 |
| `docs/adr/0012-postgresql-storage.md` | 5, 12, 14, 19, 28, 32, 82 | ADRの決定履歴・完了注記 |
| `docs/adr/0015-memory-model-reorganization.md` | 5, 56, 79 | ADRの決定履歴・完了注記 |
| `docs/adr/0016-memory-kinds-and-records.md` | 5, 119 | ADRの決定履歴・完了注記 |
| `docs/adr/0019-memory-correction-invalidation.md` | 106 | ADRの決定履歴・完了注記 |
| `docs/adr/0021-postgresql-only-storage.md` | 1, 5, 12, 13, 17, 19, 20, 24, 25, 27, 29, 33, 34, 35, 39 | ADRの決定履歴・完了注記 |
| `docs/adr/README.md` | 31, 33 | ADRの決定履歴・完了注記 |
| `docs/evidence/2026-10-03-conversation-history.md` | 14, 31 | 既存の検証履歴 |
| `docs/evidence/2026-10-03-memory.md` | 36 | 既存の検証履歴 |
| `docs/evidence/2026-10-03-privacy-boundaries.md` | 32 | 既存の検証履歴 |
| `docs/evidence/2026-10-05-local-memory-embedding.md` | 64 | 既存の検証履歴 |
| `docs/evidence/2026-10-05-postgresql-storage.md` | 22, 74 | 既存の検証履歴 |
| `docs/evidence/2026-10-07-history-test-migration.md` | 4, 9, 11, 14, 19, 24, 26, 28, 36, 43, 44, 51, 58, 78, 85, 92, 122, 126, 128, 129, 133, 136, 142, 174, 175, 184 | 既存の検証履歴 |
| `docs/evidence/2026-10-07-memory-record-contracts.md` | 128 | 既存の検証履歴 |
| `docs/evidence/2026-10-07-memory-record-store.md` | 14, 124 | 既存の検証履歴 |
| `docs/evidence/2026-10-07-memory-test-migration.md` | 9, 11, 29, 39, 60, 73, 107, 130, 145, 146, 148, 152, 160, 162, 164, 165, 169, 182, 217 | 既存の検証履歴 |
| `docs/postgresql.md` | 4 | 撤去済みの最小説明 |
| 本証跡 | 1, 4, 10, 13, 18, 19, 37, 53, 64, 83, 92, 94, 132, 140, 145, 146, 178, 203, 208, 209, 214, 255, 303, 311, 312 | 撤去の変更記録（上記以外の全自己参照） |

## 確認事項・未実施

対応表外4ファイルの47件は削除せずPostgreSQLへ移し、契約を保持した。監督側で対応表の補足として確認する。
旧設定の継続拒否試験は許可schemaの厳密一致で保証し、具体的な旧設定名の拒否はTDDと個別実行で照合した。回帰試験に旧設定文字列を残さない扱いを採用した。
実LLM・外部推論通信・実環境IT2/ST・公開CI・CodeRabbitはNOT RUN。ローカル合成試験を実環境受入へ広げない。

## 変更・削除ファイル

起点との比較。Rはhelper/契約関数の移設、Dは削除、Aは追加、Mは変更。

| 状態 | ファイル |
| --- | --- |
| M | `CONTRIBUTING.md` |
| M | `README.md` |
| M | `SPEC.md` |
| M | `docs/adr/0021-postgresql-only-storage.md` |
| M | `docs/adr/README.md` |
| A | `docs/evidence/2026-10-07-sqlite-removal.md` |
| M | `docs/history-api.md` |
| M | `docs/memory-evaluation.md` |
| M | `docs/memory.md` |
| M | `docs/postgresql.md` |
| M | `docs/privacy.md` |
| M | `docs/semantic-postgresql-integration.md` |
| D | `src/digital_souls_core/memory_sql.py` |
| D | `src/digital_souls_core/sqlite_history.py` |
| D | `src/digital_souls_core/sqlite_memory.py` |
| M | `src/digital_souls_core/storage.py` |
| A | `tests/conversation_support.py` |
| R078 | `tests/test_memory_confirmation.py` → `tests/memory_confirmation_contracts.py` |
| A | `tests/memory_support.py` |
| M | `tests/postgres_memory_support.py` |
| A | `tests/privacy_support.py` |
| M | `tests/test_conversation_controls.py` |
| D | `tests/test_conversations.py` |
| M | `tests/test_history.py` |
| M | `tests/test_history_limits.py` |
| M | `tests/test_history_llamacpp.py` |
| M | `tests/test_history_stated_at.py` |
| M | `tests/test_local_embedding_memory.py` |
| M | `tests/test_memory.py` |
| D | `tests/test_memory_context_refs.py` |
| M | `tests/test_numeric_privacy.py` |
| M | `tests/test_postgres_conversation_controls.py` |
| M | `tests/test_postgres_conversations.py` |
| M | `tests/test_postgres_history_api.py` |
| A | `tests/test_postgres_history_limits.py` |
| M | `tests/test_postgres_history_llamacpp.py` |
| M | `tests/test_postgres_history_privacy.py` |
| A | `tests/test_postgres_local_embedding_memory.py` |
| M | `tests/test_postgres_memory_confirmation.py` |
| M | `tests/test_postgres_memory_confirmation_migration.py` |
| M | `tests/test_postgres_memory_context_refs.py` |
| M | `tests/test_postgres_memory_migration.py` |
| M | `tests/test_postgres_memory_recovery.py` |
| A | `tests/test_postgres_numeric_privacy.py` |
| M | `tests/test_postgres_semantic_memory.py` |
| M | `tests/test_postgres_semantic_migration.py` |
| M | `tests/test_postgres_stated_at.py` |
| A | `tests/test_postgres_structured_memory.py` |
| M | `tests/test_postgres_turn_deletion.py` |
| M | `tests/test_postgres_turn_deletion_migration.py` |
| M | `tests/test_privacy.py` |
| D | `tests/test_semantic_memory.py` |
| M | `tests/test_storage.py` |
| M | `tests/test_structured_memory.py` |
| D | `tests/test_turn_deletion_migration.py` |
| A | `tests/time_support.py` |
| R093 | `tests/test_turn_deletion.py` → `tests/turn_deletion_contracts.py` |
