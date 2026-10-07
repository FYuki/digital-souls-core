# 履歴・会話・API試験のPostgreSQL合成試験への移植（Issue #86）

対象: [Issue #86](https://github.com/FYuki/digital-souls-core/issues/86)、Epic #79。
起点: `67baa92`、作業branch: `feature/86-history-tests-postgres`。製品コード・既存SQLite試験・既存PostgreSQL試験・共有fixtureは変更しない。

## 試験数と照合方法

pytest collectionのケース数（パラメタ化展開後）で照合した。移植前のpostgres markerは **244件**、移植後は **323件**（**79件追加**）。既存244件は維持。
全collectionは1584→1663件、既存UT/IT1は維持（SQLite撤去は#88）。実モデル・実環境のIT2/STはNOT RUN、今回の合成試験をそのPASSとは扱わない。

`git grep -il sqlite tests` は対象9ファイルと記憶担当#87の4ファイル（test_memory.py、test_semantic_memory.py、test_memory_confirmation.py、test_memory_context_refs.py）を検出した。#87のファイルは変更しない。
保存を付随的に構成するprivacy試験も移植した。保存非依存のscan/classifier/config/fingerprint/input/時計UTはプロセス内に残す。

既存turn deletion試験はPostgreSQL fixtureと同じ関数・parametrizeを使うため、全28関数/46ケースの契約が既に一致する。物理消去1件だけSQLite固有で除外。
既存stores/stated_at試験はassertionを照合し、HTTP/API・production adapter契約はstore試験で代替せず追加した。

## 個別対応表

ケース数はSQLite側の元ファイルでcollectされた数。各行のパラメタ化は全ケースを対象とし、新規移植では既存parametrizeを維持する。
ファイル物理消去のassertionは当該schemaの全table値の不在検査へ読み替えた。本文・reasoning・秘密がDBに保存されないことを検証し、PostgreSQLの旧tuple/WAL/backup消去を主張しない。

### tests/test_history.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_order_reopen_idempotency_conflict_and_delete` | 1 | 一覧・発話順、再起動、再送の冪等性、fingerprint/revision競合、削除後の保存拒否。SQLite物理消去のassertionのみ対象外 | `tests/test_postgres_stores.py::test_history_order_retry_cas_reopen_and_delete` / `tests/test_postgres_history_initialization.py::test_deleted_conversation_cannot_be_resurrected_by_late_append` |
| `test_every_store_operation_is_scoped` | 3 | subject/client/character の全store操作のBinding分離 | `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes` |
| `test_secure_defaults_and_reject_unsafe_storage` | 1 | 既定保存先、0600/0700、hardlink、Git配下、symlink、公有ディレクトリ拒否 | 移植しない：SQLite固有のファイル保存先・POSIX権限・hardlink/symlink・Git管理下制約。PostgreSQL接続境界は既存test_postgres_config.pyで検証 |
| `test_unknown_schema_is_not_overwritten` | 1 | 未知versionを上書きしないfail-closed | `tests/test_postgres_stores.py::test_unknown_schema_version_is_preserved_and_rejected` |
| `test_request_fingerprint_survives_process_hash_seed` | 1 | 異なるPYTHONHASHSEEDでも再送fingerprintが同一 | 保存に依存しないためプロセス内のまま |
| `test_first_schema_creation_recovers_after_process_exit` | 4 | DDL/版登録中の実プロセス終了後、原子的rollbackから初期化を再試行 | `tests/test_postgres_history_initialization.py::test_first_schema_creation_recovers_after_process_exit` |
| `test_unknown_unversioned_schema_still_fails_closed` | 1 | versionなしの未知table/本文を保存して初期化を拒否 | `tests/test_postgres_history_initialization.py::test_unknown_unversioned_schema_is_preserved_and_rejected` |

### tests/test_history_stated_at.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_utc_normalization_preserves_instant_and_rejects_naive_time` | 1 | UTC正規化で瞬間を維持、naive日時を拒否 | 保存に依存しないためプロセス内のまま |
| `test_current_utc_returns_current_aware_time` | 1 | 現在のaware UTC日時 | 保存に依存しないためプロセス内のまま |
| `test_clock_is_sampled_per_turn_and_restored_for_every_message` | 1 | turnごとの時計、tool含む全発話の保存日時、再送は時計を再採取しない | `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_snapshot_and_single_and_batch_evidence` |
| `test_default_clock_records_current_utc_at_append` | 1 | 既定時計の保存日時がappendの前後内にある | `tests/test_postgres_stated_at.py::test_new_schema_is_v5_and_default_clock_is_current_utc` |
| `test_naive_clock_rejects_without_turn_or_revision_and_allows_retry` | 1 | naive時計拒否でturn/revision/receiptをrollback、正常時計で再試行 | `tests/test_postgres_stated_at.py::test_naive_clock_rolls_back_and_valid_retry_saves_timestamp` |
| `test_legacy_migration_preserves_null_receipt_fingerprint_and_evidence` | 3 | 旧版日時NULL、receipt/fingerprint、Evidence/source epoch、再送と新turn日時を保持 | SQLite user_version 1/2/3は移植しない。保持契約は `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence` で検証 |
| `test_v4_migration_process_exit_rolls_back_then_retries` | 2 | SQLite user_version/ALTER途中のプロセス終了rollback | SQLite固有user_version 3→4とtrace_callbackによる終了は移植しない。PostgreSQL列/版登録のrollbackは `tests/test_postgres_stated_at.py::test_v1_migration_interruption_rolls_back_and_retries`、実プロセス終了は新規initialization試験で検証 |
| `test_evidence_uses_saved_time_without_changing_source_or_job_identity` | 1 | Evidenceの保存日時、source/epoch/job IDと再起動後の冪等性 | `tests/test_postgres_stated_at.py::test_fixed_clock_reopen_snapshot_and_single_and_batch_evidence` |
| `test_http_completion_get_and_patch_preserve_turn_times` | 2 | HTTP非stream/stream、tool往復、再送、GET/PATCHで日時を保持、Messageに日時を追加しない | `tests/test_postgres_history_api.py::test_http_completion_get_and_patch_preserve_turn_times`（新規、全ケース移植） |
| `test_legacy_http_null_and_service_retry_do_not_infer_again` | 1 | 旧turnのHTTP日時NULLと既存receipt再送によるモデル呼出しの省略 | `tests/test_postgres_history_api.py::test_legacy_http_null_and_service_retry_do_not_infer_again`（新規、全ケース移植） |

### tests/test_history_llamacpp.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_history_with_production_local_adapter` | 6 | 実SDK/production local adapterを合成transportで検証、text/tools/stream/stream_tools/timeout/cancel、再起動再送、次turn文脈、transport close、秘密の保存拒否 | `tests/test_postgres_history_llamacpp.py::test_history_with_production_local_adapter`（新規、全ケース移植） |
| `test_local_endpoint_is_part_of_retry_identity` | 1 | local endpoint変更で再送fingerprintが変わる | 保存に依存しないためプロセス内のまま |

### tests/test_conversations.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_restore_retry_and_new_turn_context` | 1 | 再起動/再送冪等性、変更入力拒否、次turn文脈、scope変更拒否 | `tests/test_postgres_conversations.py::test_restore_retry_and_new_turn_context`（新規、全ケース移植） |
| `test_tool_roundtrip` | 2 | 非stream/streamでtool ID照合、順序・複数result、再送 | `tests/test_postgres_conversations.py::test_tool_roundtrip`（新規、全ケース移植） |
| `test_failed_stream_never_persists` | 7 | initial/middle/unfinished/length/reasoning/secret/tool失敗でturn非保存、close、秘密非保存 | `tests/test_postgres_conversations.py::test_failed_stream_never_persists`（新規、全ケース移植） |
| `test_reasoning_fields_are_not_saved` | 1 | 非stream/streamのreasoning_contentを保存しない | `tests/test_postgres_conversations.py::test_reasoning_fields_are_not_saved`（新規、全ケース移植） |
| `test_policy_fail_closed_on_each_boundary_and_delete_after_revocation` | 1 | store/read/export拒否、秘密拒否、壊れた/欠落policyのfail-closed、許可撤回後も削除可能 | `tests/test_postgres_conversations.py::test_policy_fail_closed_on_each_boundary_and_delete_after_revocation`（新規、全ケース移植） |
| `test_inflight_boundaries` | 8 | 非stream/streamのcancel/delete/revoke/concurrent時に遅い保存を拒否 | `tests/test_postgres_conversations.py::test_inflight_boundaries`（新規、全ケース移植） |
| `test_http_opt_in_crud_stream_and_reject_scope` | 1 | HTTP opt-in、policy必須、CRUD、stream/再送、callerのscope等注入拒否 | `tests/test_postgres_conversations.py::test_http_opt_in_crud_stream_and_reject_scope`（新規、全ケース移植） |
| `test_export_revocation_during_context_lookup` | 2 | 非stream/streamのcontext await中のexport撤回でモデル送信・保存を拒否 | `tests/test_postgres_conversations.py::test_export_revocation_during_context_lookup`（新規、全ケース移植） |
| `test_http_disconnect_discards_uncommitted_turn` | 2 | 非stream/streamのHTTP切断で未commit turnを破棄、DONE抑止・close | `tests/test_postgres_conversations.py::test_http_disconnect_discards_uncommitted_turn`（新規、全ケース移植） |
| `test_fragmented_stream_tool_arguments_and_multiple_results` | 1 | 断片tool argumentsの結合と複数result往復 | `tests/test_postgres_conversations.py::test_fragmented_stream_tool_arguments_and_multiple_results`（新規、全ケース移植） |
| `test_size_role_and_invalid_output_rejections` | 1 | 過大入力・system/assistant偽造・不正finishを拒否して保存しない | `tests/test_postgres_conversations.py::test_size_role_and_invalid_output_rejections`（新規、全ケース移植） |
| `test_concurrent_retry_reauthorizes_actual_winner_receipt` | 2 | 非stream/streamの同一request競合で実際のwinnerを再認可、拒否後もreceipt/日時不変 | `tests/test_postgres_conversations.py::test_concurrent_retry_reauthorizes_actual_winner_receipt`（新規、全ケース移植） |
| `test_same_tick_disconnect_and_provider_completion` | 4 | 非stream/stream×両ready-queue順序で同時切断・完了時にcommitせず再送可能 | `tests/test_postgres_conversations.py::test_same_tick_disconnect_and_provider_completion`（新規、全ケース移植） |
| `test_delivery_failure_after_commit_keeps_retry_receipt` | 2 | 非stream/streamのHTTP送信失敗後もcommit済receiptで再送し推論を重複しない | `tests/test_postgres_conversations.py::test_delivery_failure_after_commit_keeps_retry_receipt`（新規、全ケース移植） |
| `test_sdk_profile_defaults_preserve_pre_llamacpp_receipt` | 1 | 固定旧fingerprintのSDK default receiptを再利用し推論しない | `tests/test_postgres_conversations.py::test_sdk_profile_defaults_preserve_pre_llamacpp_receipt`（新規、全ケース移植） |

### tests/test_conversation_controls.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_explicit_excluded_utterance_preserves_history_and_retry` | 1 | 指定user除外と履歴保持・再送identity、再起動後の適格性 | `tests/test_postgres_conversation_controls.py::test_explicit_excluded_utterance_preserves_history_and_retry`（新規、全ケース移植） |
| `test_thread_private_then_public_does_not_retroactively_admit_private_turn` | 1 | private中保存turnはpublic化後も非適格、前の公開sourceだけ再適格 | `tests/test_postgres_conversation_controls.py::test_thread_private_then_public_does_not_retroactively_admit_private_turn`（新規、全ケース移植） |
| `test_archive_only_changes_listing_and_preserves_memory_source` | 1 | HTTP archive/include_archivedとstale revision拒否、source保持 | `tests/test_postgres_conversation_controls.py::test_archive_only_changes_listing_and_preserves_memory_source`（新規、全ケース移植） |
| `test_delete_atomically_notifies_and_invalidates_sources` | 1 | 許可撤回後の削除・再送、内容なし通知の永続性/Binding分離/ACK、source無効化 | `tests/test_postgres_conversation_controls.py::test_delete_atomically_notifies_and_invalidates_sources`（新規、全ケース移植） |
| `test_delete_event_and_history_deletion_rollback_together` | 1 | 削除失敗で履歴・revision・通知を同時rollback | `tests/test_postgres_stores.py::test_failed_revocation_rolls_back_history_memory_and_outboxes_together` |
| `test_v1_upgrade_preserves_history_and_receipt` | 3 | SQLite user_version移行と中断再試行、既存履歴/receipt保持 | SQLite固有user_version/ALTER移行3ケースは移植しない。PostgreSQL保持・中断再試行は `tests/test_postgres_stated_at.py::test_v1_migration_preserves_old_null_history_receipt_and_evidence` / `tests/test_postgres_stated_at.py::test_v1_migration_interruption_rolls_back_and_retries` で検証 |
| `test_private_change_conflicts_with_inflight_inference` | 1 | private化とinflight推論のrevision競合で遅いturn保存を拒否 | `tests/test_postgres_conversation_controls.py::test_private_change_conflicts_with_inflight_inference`（新規、全ケース移植） |
| `test_invalid_message_exclusions_rejected` | 4 | TurnInputの除外indices（負/範囲外/重複/bool）を拒否 | 保存に依存しないためプロセス内のまま |
| `test_excluded_history_cannot_reenter_via_later_assistant` | 2 | 明示除外/private履歴のassistant引用はuser sourceに再採用しない | `tests/test_postgres_conversation_controls.py::test_excluded_history_cannot_reenter_via_later_assistant`（新規、全ケース移植） |

### tests/test_turn_deletion.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_deletion_scopes_preserve_only_untargeted_history_and_memory` | 2 | selected/throughの往復削除範囲と残す履歴/記憶 | `tests/test_postgres_turn_deletion.py::test_deletion_scopes_preserve_only_untargeted_history_and_memory`（既存、全ケース同一関数） |
| `test_whole_conversation_deletion_preserves_existing_notification_contract` | 1 | 全会話削除の既存通知/撤回契約 | `tests/test_postgres_turn_deletion.py::test_whole_conversation_deletion_preserves_existing_notification_contract`（既存、全ケース同一関数） |
| `test_multisource_memory_rebuild_uses_only_remaining_turns` | 1 | 複数source記憶を残ったturnだけから再構築 | `tests/test_postgres_turn_deletion.py::test_multisource_memory_rebuild_uses_only_remaining_turns`（既存、全ケース同一関数） |
| `test_later_saved_and_new_user_turns_remain_extractable` | 1 | 後続の保存済/新user turnの抽出可能性 | `tests/test_postgres_turn_deletion.py::test_later_saved_and_new_user_turns_remain_extractable`（既存、全ケース同一関数） |
| `test_partial_deletion_does_not_admit_retained_private_or_excluded_source` | 2 | 部分削除でprivate/明示除外sourceを適格化しない | `tests/test_postgres_turn_deletion.py::test_partial_deletion_does_not_admit_retained_private_or_excluded_source`（既存、全ケース同一関数） |
| `test_tool_call_result_chain_expands_deletion_in_both_directions` | 4 | tool call/result chainを双方向へ削除展開 | `tests/test_postgres_turn_deletion.py::test_tool_call_result_chain_expands_deletion_in_both_directions`（既存、全ケース同一関数） |
| `test_tool_identifiers_in_content_do_not_expand_deletion` | 6 | 本文内のtool識別子は削除展開しない（6ケース） | `tests/test_postgres_turn_deletion.py::test_tool_identifiers_in_content_do_not_expand_deletion`（既存、全ケース同一関数） |
| `test_deleted_request_retry_is_rejected_after_restart` | 2 | 削除済requestの同一/変更再送を再起動後も拒否 | `tests/test_postgres_turn_deletion.py::test_deleted_request_retry_is_rejected_after_restart`（既存、全ケース同一関数） |
| `test_partial_deletion_rejects_same_inflight_http_completion` | 2 | 非stream/streamの同一inflight HTTP完了を部分削除後に保存しない | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_http_completion`（既存、全ケース同一関数） |
| `test_partial_deletion_rejects_same_inflight_completion` | 2 | 非stream/streamの同一inflight service完了を部分削除後に保存しない | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_completion`（既存、全ケース同一関数） |
| `test_partial_deletion_invalidates_same_prepared_memory_context` | 1 | 準備済み記憶contextを部分削除で無効化 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_invalidates_same_prepared_memory_context`（既存、全ケース同一関数） |
| `test_partial_deletion_rejects_same_inflight_extraction` | 1 | 部分削除が同一inflight抽出のcommitを拒否 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_rejects_same_inflight_extraction`（既存、全ケース同一関数） |
| `test_remaining_dates_confirmation_states_and_receipts_survive_restart` | 1 | 残る日時/確認保留/receiptを再起動後も保持 | `tests/test_postgres_turn_deletion.py::test_remaining_dates_confirmation_states_and_receipts_survive_restart`（既存、全ケース同一関数） |
| `test_partial_notification_is_durable_scoped_and_contains_only_identifiers` | 1 | 部分通知は永続・Binding分離・識別子のみ | `tests/test_postgres_turn_deletion.py::test_partial_notification_is_durable_scoped_and_contains_only_identifiers`（既存、全ケース同一関数） |
| `test_retained_accepted_confirmation_stays_ineligible_after_partial_delete` | 1 | 残る受諾済確認を部分削除で再適格化しない | `tests/test_postgres_turn_deletion.py::test_retained_accepted_confirmation_stays_ineligible_after_partial_delete`（既存、全ケース同一関数） |
| `test_invalid_deletion_leaves_all_state_unchanged` | 2 | 不正revision/turn削除で全状態不変 | `tests/test_postgres_turn_deletion.py::test_invalid_deletion_leaves_all_state_unchanged`（既存、全ケース同一関数） |
| `test_partial_deletion_remains_available_after_consent_revocation` | 1 | 許可撤回後も部分削除可能 | `tests/test_postgres_turn_deletion.py::test_partial_deletion_remains_available_after_consent_revocation`（既存、全ケース同一関数） |
| `test_failed_delete_rolls_back_revision_history_memory_and_allows_retry` | 1 | 失敗削除でrevision/履歴/記憶rollback、再試行可能 | `tests/test_postgres_turn_deletion.py::test_failed_delete_rolls_back_revision_history_memory_and_allows_retry`（既存、全ケース同一関数） |
| `test_natural_language_does_not_delete_history` | 1 | 自然言語は履歴削除の操作権限を持たない | `tests/test_postgres_turn_deletion.py::test_natural_language_does_not_delete_history`（既存、全ケース同一関数） |
| `test_deleted_tail_revision_is_never_reused` | 1 | 削除した末尾revisionを再利用しない | `tests/test_postgres_turn_deletion.py::test_deleted_tail_revision_is_never_reused`（既存、全ケース同一関数） |
| `test_same_tool_name_with_different_ids_does_not_join_independent_turns` | 1 | 同じtool名でも異なるIDのturnを結合しない | `tests/test_postgres_turn_deletion.py::test_same_tool_name_with_different_ids_does_not_join_independent_turns`（既存、全ケース同一関数） |
| `test_multiple_calls_and_results_are_deleted_together` | 1 | 複数call/resultをまとめて削除 | `tests/test_postgres_turn_deletion.py::test_multiple_calls_and_results_are_deleted_together`（既存、全ケース同一関数） |
| `test_invalid_deletion_input_is_rejected_without_changes` | 5 | 不正delete input 5ケースで状態不変 | `tests/test_postgres_turn_deletion.py::test_invalid_deletion_input_is_rejected_without_changes`（既存、全ケース同一関数） |
| `test_partial_deletion_cannot_change_another_binding` | 1 | 別Bindingの部分削除は状態を変更しない | `tests/test_postgres_turn_deletion.py::test_partial_deletion_cannot_change_another_binding`（既存、全ケース同一関数） |
| `test_repeated_partial_deletion_is_rejected_without_second_revision_change` | 1 | 繰り返し部分削除でrevisionを二重更新しない | `tests/test_postgres_turn_deletion.py::test_repeated_partial_deletion_is_rejected_without_second_revision_change`（既存、全ケース同一関数） |
| `test_rebuild_revalidates_job_after_another_partial_deletion` | 1 | 別の部分削除後に再構築jobを再検証 | `tests/test_postgres_turn_deletion.py::test_rebuild_revalidates_job_after_another_partial_deletion`（既存、全ケース同一関数） |
| `test_rebuild_failure_never_restores_deleted_memory_body` | 1 | 再構築失敗時も消去した本文を復活しない | `tests/test_postgres_turn_deletion.py::test_rebuild_failure_never_restores_deleted_memory_body`（既存、全ケース同一関数） |
| `test_tombstone_keeps_request_identifier_without_content_or_fingerprint` | 1 | tombstoneはrequest識別子だけ保持し本文/fingerprintを残さない | `tests/test_postgres_turn_deletion.py::test_tombstone_keeps_request_identifier_without_content_or_fingerprint`（既存、全ケース同一関数） |
| `test_sqlite_partial_deletion_physically_erases_source_and_derived_text` | 1 | SQLite物理ファイルの逐語/派生本文消去 | 移植しない：SQLite固有のsecure_delete/物理ファイル消去。PostgreSQLは論理的取得停止・本文NULL化のみを保証しWAL/媒体の物理消去を保証しない |

### tests/test_turn_deletion_migration.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_v5_migration_preserves_stored_time_confirmation_and_receipt` | 6 | 旧版のNULL/保存日時×確認pending/false/true、receipt/source適格性を保持して削除可能 | SQLite user_version 5→6は移植しない。NULL/日時×3確認状態の6ケースは既存 `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_preserves_stored_time_confirmation_and_receipt` が同じ契約を検証 |
| `test_v5_migration_interruption_rolls_back_and_allows_retry` | 1 | SQLite user_version 5→6のDDL/version/rows原子的rollbackと再試行 | SQLite user_version 5→6は移植しない。保持/rollback/再試行は既存 `tests/test_postgres_turn_deletion_migration.py::test_v3_migration_interruption_rolls_back_and_allows_retry` が検証 |

### tests/test_storage.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_ambiguous_config_is_rejected` | 7 | StorageConfig曖昧設定/未知field/混合backendを拒否（7ケース） | 保存に依存しないためプロセス内のまま |
| `test_sqlite_stores_share_explicit_database` | 1 | 明示factoryでhistory/memoryを同じDBへ構成、自動抽出しない | `tests/test_postgres_history_initialization.py::test_factory_shares_explicit_database_without_extracting` |
| `test_postgres_factory_shares_database_and_does_not_extract` | 1 | factoryが同じDBインスタンスを両adapterへ渡す（constructorのみ差替え） | 保存に依存しないためプロセス内のまま |
| `test_construct_cannot_bypass_backend_validation` | 1 | model_constructでもfactoryで再検証 | 保存に依存しないためプロセス内のまま |

### tests/test_privacy.py

| SQLite側/現行試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験、または移植しない理由 |
| --- | ---: | --- | --- |
| `test_synthetic_secret_corpus` | 14 | 合成秘密14形式のscan | 保存に依存しないためプロセス内のまま |
| `test_benign_corpus` | 5 | 一般文/構造のscanで秘密誤検出しない | 保存に依存しないためプロセス内のまま |
| `test_documented_detection_limits_and_fail_closed` | 1 | scanの型/サイズ/深さ制限と検出限界 | 保存に依存しないためプロセス内のまま |
| `test_default_denial` | 4 | history/local/external/memory許可の既定拒否 | 保存に依存しないためプロセス内のまま |
| `test_secret_never_reaches_classifier_or_history` | 5 | user/assistant/tool args/result/schemaの秘密をclassifier・履歴・receipt・ログへ保存しない | `tests/test_postgres_history_privacy.py::test_secret_never_reaches_classifier_or_history`（新規、全ケース移植） |
| `test_natural_language_does_not_change_operation_scope` | 4 | 自然言語は操作scopeを変更せず明示除外だけを適用 | `tests/test_postgres_history_privacy.py::test_natural_language_does_not_change_operation_scope`（新規、全ケース移植） |
| `test_natural_language_without_exclusion_holds_source_for_confirmation` | 4 | 除外指示に見える自然言語は保存し確認保留でsource非適格 | `tests/test_postgres_history_privacy.py::test_natural_language_without_exclusion_holds_source_for_confirmation`（新規、全ケース移植） |
| `test_local_external_memory_permissions_and_sensitive_history` | 1 | local/external/memory許可を分離、機微履歴・local consent・別Binding拒否 | `tests/test_postgres_history_privacy.py::test_local_external_memory_permissions_and_sensitive_history`（新規、全ケース移植） |
| `test_classifier_strict_fail_closed` | 8 | classifier出力の不正schema/JSON/版等8ケースを拒否 | 保存に依存しないためプロセス内のまま |
| `test_classifier_secret_exception_and_missing_policy` | 1 | 秘密/例外/欠落policyのfail-closed、秘密非ログ | 保存に依存しないためプロセス内のまま |
| `test_revocation_during_classifier_wait` | 1 | classifier await中の許可撤回で送信を拒否（保存は付随的に構成） | `tests/test_postgres_history_privacy.py::test_revocation_during_classifier_wait`（新規、全ケース移植） |
| `test_retry_and_output_recheck_current_grants` | 1 | 再送/出力で現在のgrantsを再照合、許可撤回後削除 | `tests/test_postgres_history_privacy.py::test_retry_and_output_recheck_current_grants`（新規、全ケース移植） |
| `test_stream_secret_split_never_saved` | 1 | stream断片に分かれた秘密を保存せずclose | `tests/test_postgres_history_privacy.py::test_stream_secret_split_never_saved`（新規、全ケース移植） |
| `test_actual_payload_injection_blocked` | 3 | system/lore/contextの実payload秘密をclassifier/modelへ送らない（保存は付随的に構成） | `tests/test_postgres_history_privacy.py::test_actual_payload_injection_blocked`（新規、全ケース移植） |
| `test_classifier_failure_lifecycle` | 5 | classifier timeout/cancel/length/multiple/tool失敗とclose | 保存に依存しないためプロセス内のまま |
| `test_classifier_existing_sdk_transport` | 1 | classifierの既存SDK transportとjson_schema、合成認証情報の送信抑止 | 保存に依存しないためプロセス内のまま |
| `test_policy_replacement_prevents_context_lookup` | 1 | classifier await中のpolicy交換でcontext lookupを拒否（保存は付随的に構成） | `tests/test_postgres_history_privacy.py::test_policy_replacement_prevents_context_lookup`（新規、全ケース移植） |
| `test_history_policy_cannot_be_disconnected` | 1 | historyとinferenceのprivacyを切り離した保存を拒否 | `tests/test_postgres_history_privacy.py::test_history_policy_cannot_be_disconnected`（新規、全ケース移植） |
| `test_nested_and_separated_secret_patterns` | 3 | 入れ子/分離秘密パターンのscan | 保存に依存しないためプロセス内のまま |
| `test_classifier_requires_operator_capabilities` | 2 | classifier profileのoperator capabilityを必須化 | 保存に依存しないためプロセス内のまま |
| `test_classifier_provenance_is_content_free` | 1 | classifier provenanceに本文を含めない | 保存に依存しないためプロセス内のまま |
| `test_classifier_setter_generation_catches_await_aba` | 1 | classifier setter generationでawait ABAを検出 | 保存に依存しないためプロセス内のまま |

## ケース数の内訳・重複回避

新規: conversations 36件、conversation_controls 7件、history_llamacpp 6件、history_privacy 22件、history_api 3件、history_initialization 5件、合計79件。
全store操作Binding分離は既存PostgreSQL試験がsubject/client/characterにaudienceを加えて検証する。
日時の既存固定時計試験はsnapshotとsingle/batch Evidence、job identityまで検証するため複製しない。
削除rollbackは既存試験がhistory・memory本文・通知の全状態を検証するため複製しない。

SQLite初期化中終了4ケースは「DDL・user_version登録」とSQLite内の旧版ALTER/版更新を含む。PostgreSQLの新規初期化はDDL後/版登録後の実プロセス終了2ケースを追加し、schema全体がrollbackして消えることと再試行後の全table/版を確認する。SQLite固有のALTER段階2ケースは移植しない。
SQLite legacy日時移行の3版およびSQLite controls/turn-deletionのuser_version移行はSQLite固有。PostgreSQLに存在する旧schema versionの既存試験を対応表に挙げ、契約を落とした件数減少として扱わない。

## TDD・実行証跡

全コマンドは固定uv/Node toolchain、一時先を共有メモリに指定、モデル費用mapのローカル読込みを使用。
新規fixtureは既存stores fixtureを再利用し、4つの `DSC_TEST_POSTGRES_*` を必須にする。各ケースで一意なschemaを作成し、そのschemaだけをfinallyで削除する。fake保存先は使用しない。

1. 移植前の `uv run --no-sync pytest -m postgres --collect-only -q` で244件を確認。
2. 元のservice/HTTP/SDK/privacy/controls assertionを移植して先に追加。fixtureのhistory接続は `NotImplementedError` の未実装状態にし、`bash tools/test-postgres.sh` を実行。**Red: 71 FAIL、244 PASS、1340 deselected、SKIP 0**。71件すべてが未実装history fixtureで失敗。これは新しいfixture未実装のRedであり、製品adapterの回帰によるRedではない。
3. history fixtureを実際の `PostgresDatabase` / `PostgresHistory` に接続。HTTP日時・実factory・未知schema・初期化終了・遅いappendの8ケースも追加。**初回Green試行: 1 FAIL、322 PASS、SKIP 0**。遅いappend試験に追加したエラーコードの期待値を誤って `conversation_not_found` としたため。元のSQLite試験はCoreError拒否のみを契約としており、現行append契約の `revision_conflict` に修正。製品コードは変更していない。
4. PostgreSQL設定4変数未指定でHTTP日時の1ケースを `--maxfail=1` 実行。**1 fixture ERROR、SKIP 0**。設定不足をSKIPへ逃がさず、DBなしでPASSしないことを確認（意図した失敗）。
5. fixture修正後の全ゲートは下表。DBはdigest固定PostgreSQL 18のネットワークなし・公開portなし・使い捨てコンテナ、合成データのみ。provider/HTTP transportは合成応答で実LLM・外部通信なし。

## 品質ゲート

すべて固定toolchain・合成データで実行。テスト件数はparametrize展開後。最終必須ゲートにFAIL/SKIPなし。

| コマンド | 結果 | 件数・内容 |
| --- | --- | --- |
| `uv sync --frozen` | PASS | 78 package install、lock変更なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS | 違反0件 |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS | 95ファイル |
| `uv run --no-sync mypy` | PASS | 95 source files、問題0件 |
| `uv run --no-sync pytest -m ut -q` | PASS | 477 PASS、1186 deselected、SKIP 0 |
| `uv run --no-sync pytest -m it1 -q` | PASS | 863 PASS、800 deselected、SKIP 0 |
| `uv build --no-build-isolation` | PASS | sdist/wheel 2 artifact |
| `bash tools/test-postgres.sh` | PASS | 323 PASS、1340 deselected、SKIP 0 |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 23 required tests、skip/todo/cancel 0 |
| `node tools/check-docs.mjs` | PASS | 追跡対象textとローカルMarkdown参照、エラー0件 |
| `git diff --check` / `git diff --cached --check` | PASS | 空白エラー0件 |

pytestの警告はUT 1件、IT1/PostgreSQL各3件（依存libraryのdeprecated BlockingPortal aliasとTypedDict ReadOnly qualifier）。FAIL/SKIPではない。

## 確認事項

製品adapterの欠陥は検出していない。仕様解釈の確認待ちはない。
実モデル・実環境のIT2/STは範囲外でNOT RUN。push・PR作成・merge・Issue操作は監督担当で未実施。
