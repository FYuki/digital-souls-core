# 記憶試験のPostgreSQL移植（2026-10-07）

対象: [Issue #87](https://github.com/FYuki/digital-souls-core/issues/87)、
[Epic #79](https://github.com/FYuki/digital-souls-core/issues/79)、
[ADR 0021](../adr/0021-postgresql-only-storage.md)。

## 範囲と環境

起点は `epic/sqlite-retirement` の `67baa92890de6803c6a4ff44f16391e55c1fe638`。
試験・証跡のrevisionは本書を含むcommit（最終報告のSHAで特定）です。
製品コード・既存SQLite試験・既存PostgreSQL試験・共有conftest/supportは変更していません。
#86の履歴・会話・API試験、push・PR・merge・Issue操作も対象外です。

Python 3.12.3、uv 0.8.22、Node 24.19.0、固定lock依存を使用しました。
固定toolchainのbinディレクトリをPATHの先頭に置き、全試験に `TMPDIR=/dev/shm` と
`LITELLM_LOCAL_MODEL_COST_MAP=True` を設定しています。後者でLiteLLMの外部価格取得を抑止します。
PostgreSQLは `tools/test-postgres.sh` のdigest固定PostgreSQL 18公式イメージです。
Dockerのネットワークはnone、公開portなし、データはtmpfs、専用Unix socketで接続します。
合成履歴・合成provider応答・決定的なプロセス内vectorのみで、実LLM・実環境は使いません。

新規試験も既存stores fixtureを使い、接続設定欠落はSKIPではなくFAILです。
各ケースで別の一意schemaを生成し、そのschemaだけをfinallyで削除します。
保存portはPostgresHistory/PostgresMemoryです。provider/encoderの障害注入は既存契約を保持するためで、
fake保存先は追加していません。

## ケース件数

件数はpytestの収集結果です。パラメタ化をケース単位で数えています。
既存SQLite試験は#88まで残すのでUT/IT1の件数は減少しません。

| 範囲 | 移植前 | 移植後 | 差分 |
| --- | ---: | ---: | ---: |
| postgres marker全体 | 244 | 400 | +156 |
| UT | 477 | 477 | 0 |
| IT1 | 863 | 863 | 0 |
| 対象4ファイルの既存ケース | 215 | 215 | 0（削除なし） |

対象215件のうち、156件を新規PostgreSQL試験へ移植、51件は既存PostgreSQL試験で対応済み、
5件はSQLite固有migration、3件は保存非依存として残します。合計215件です。
既存対応は機能名だけで判定せず、出典epoch・即時本文消去・再構築・Binding各軸・順位・送信前guard・保留を照合しました。
既存対応試験に他の追加パラメタがある場合も、ここでは元ケースに対応する件数だけを数えています。

| 新規ファイル | postgresケース数 |
| --- | ---: |
| `tests/test_postgres_memory_migration.py` | 91 |
| `tests/test_postgres_semantic_migration.py` | 52 |
| `tests/test_postgres_memory_context_refs.py` | 9 |
| `tests/test_postgres_memory_confirmation_migration.py` | 2 |
| `tests/test_postgres_memory_recovery.py` | 2 |
| 合計 | 156 |

## 契約対応表

同一関数の全パラメタに同じ対応がある場合は1行にまとめ、ケース数を示します。
部分的な既存対応（outboxの3中断点、awaitの18組合せ）は行を分けます。
「新規」は今回の移植、「既存」は起点で既に実行されていた試験です。

### `test_memory.py`

| SQLite側の試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験または理由 |
| --- | ---: | --- | --- |
| `test_extract_restore_search_archive_and_retry` | 2 | episode/semanticの本文・出典epoch、冪等抽出、再open、archive後も検索 | 新規: `tests/test_postgres_memory_migration.py::test_extract_restore_search_archive_and_retry` |
| `test_multisource_revocation_erases_body_and_rebuilds_remaining` | 2 | private→解除/会話削除で即時本文NULL・旧ID停止、通知冪等消費、残存出典だけ再抽出、新epochでのみ再採用 | 新規: `tests/test_postgres_memory_migration.py::test_multisource_revocation_erases_body_and_rebuilds_remaining` |
| `test_more_revocations_after_job_creation_never_restore_sources` | 1 | job作成後の追加撤回、逆順・重複通知、根拠ゼロ時は再構築なし | 新規: `tests/test_postgres_memory_migration.py::test_more_revocations_after_job_creation_never_restore_sources` |
| `test_memory_scope_never_crosses_sources_results_events` | 4 | subject/client/audience/character各軸の出典・結果・通知分離と別Bindingのconsume無効 | 既存: `tests/test_postgres_stores.py::test_scope_isolation_covers_history_memory_jobs_and_outboxes` |
| `test_non_user_or_ineligible_sources_never_reach_extractor` | 4 | assistant/tool/明示除外/privateの出典を抽出器へ送信しない | 新規: `tests/test_postgres_memory_migration.py::test_non_user_or_ineligible_sources_never_reach_extractor` |
| `test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs` | 9 | 不正JSON、重複key/index、未知schema/kind、範囲外index、余剰field、過大出力を拒否しjobのみ再試行可能 | 新規: `tests/test_postgres_memory_migration.py::test_strict_extraction_rejects_unknown_ambiguous_or_unbounded_outputs` |
| `test_secret_is_rejected_before_classifier_or_extractor` | 1 | 秘密を含む保存済みuser出典を分類器・抽出器・job登録前に拒否 | 新規: `tests/test_postgres_memory_migration.py::test_secret_is_rejected_before_classifier_or_extractor` |
| `test_revoke_during_extractor_await_no_commit_or_next_classification` | 4 | 抽出await中のprivate/削除/policy/classifier変更で採用せずDBに記憶0件 | 新規: `tests/test_postgres_memory_migration.py::test_revoke_during_extractor_await_no_commit_or_next_classification` |
| `test_context_provenance_survives_final_classifier_await` | 2 | JSON/SSE最終payloadの分類await中の撤回でprovider送信・履歴appendなし | 新規: `tests/test_postgres_memory_migration.py::test_context_provenance_survives_final_classifier_await` |
| `test_context_opt_in_stateless_compatibility_and_dispatch_guard` | 1 | statelessでは検索せずconversationでのみcontext、返却後撤回はcheckで拒否 | 新規: `tests/test_postgres_memory_migration.py::test_context_opt_in_stateless_compatibility_and_dispatch_guard` |
| `test_extraction_timeout_cancel_is_retryable` | 2 | 抽出timeout/cancelで採用せずpendingを保持 | 新規: `tests/test_postgres_memory_migration.py::test_extraction_timeout_cancel_is_retryable` |
| `test_v2_memory_migration_recovers_without_losing_history` | 5 | SQLite v2→記憶DDL・PRAGMA更新の各中断点でrollbackし履歴/receipt/epoch保持 | 移植しない: SQLiteのv2 history-only schemaへの5つのDDL/PRAGMA中断点。PostgreSQL v1には既に記憶表があり、このschema段階・SQLite subprocess trace callbackは存在しない。一般の原子性は下記outbox/既存PostgreSQL rollback試験で保持。 |
| `test_revocation_outbox_crash_replays_atomically`（UPDATE memories SET body=NULL） | 1 | 本文消去・job登録・通知処理済み更新の中断は原子的にrollback、再open/再試行で残る出典だけ再構築 | 既存: `tests/test_postgres_stores.py::test_failed_revocation_rolls_back_history_memory_and_outboxes_together` のaction=delete |
| `test_revocation_outbox_crash_replays_atomically`（INSERT OR IGNORE INTO memory_jobs） | 1 | 本文消去・job登録・通知処理済み更新の中断は原子的にrollback、再open/再試行で残る出典だけ再構築 | 新規: `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically` のstage=job_insert |
| `test_revocation_outbox_crash_replays_atomically`（UPDATE memory_events SET processed=1） | 1 | 本文消去・job登録・通知処理済み更新の中断は原子的にrollback、再open/再試行で残る出典だけ再構築 | 新規: `tests/test_postgres_memory_recovery.py::test_interrupted_outbox_consume_replays_atomically` のstage=event_processed |
| `test_memory_policy_mismatch_rejected_before_old_classifier` | 1 | inferenceとmemoryのpolicy object不一致を旧分類器の送信前に拒否 | 新規: `tests/test_postgres_memory_migration.py::test_memory_policy_mismatch_rejected_before_old_classifier` |
| `test_extractor_envelope_and_secret_failure_has_no_stored_candidate` | 6 | reasoning/tool/途中終了/choices欠落/provider例外/secretを内容なしで拒否し候補・秘密を保存しない | 新規: `tests/test_postgres_memory_migration.py::test_extractor_envelope_and_secret_failure_has_no_stored_candidate` |
| `test_extractor_rejects_unmanaged_or_unpinned_profiles` | 1 | 管理外transport/endpoint/送信許可/parameter設定を生成時に拒否 | 保存に依存しないためプロセス内のまま（既存it1 markerを保持） |
| `test_concurrent_retries_commit_once_and_preserve_canonical_sources` | 1 | 出典逆順の並行抽出は同じ結果・job1件・記憶1件 | 新規: `tests/test_postgres_memory_migration.py::test_concurrent_retries_commit_once_and_preserve_canonical_sources` |
| `test_search_is_bounded` | 4 | 空/257文字query、limit0/17を拒否 | 既存: `tests/test_postgres_stores.py::test_memory_query_bounds` |
| `test_failed_rebuild_leaves_old_id_invisible_and_can_retry` | 1 | 再構築失敗は旧ID/本文を復活させずfailed終端、明示extractだけで新ID登録 | 新規: `tests/test_postgres_memory_migration.py::test_failed_rebuild_leaves_old_id_invisible_and_can_retry` |
| `test_inference_policy_swap_at_lookup_await_stops_old_memory_send` | 2 | base context/query分類awaitでpolicy交換した時に旧記憶を分類器へ送らない | 新規: `tests/test_postgres_memory_migration.py::test_inference_policy_swap_at_lookup_await_stops_old_memory_send` |
| `test_secret_provenance_is_rejected_before_persistence` | 1 | 秘密のprovenanceはjob・記憶の登録前に拒否 | 新規: `tests/test_postgres_memory_migration.py::test_secret_provenance_is_rejected_before_persistence` |
| `test_synthetic_protocol_corpus_not_model_quality` | 6 | 合成corpus6件のepisode/semantic/対象外、選択出典からの本文形成（モデル精度の評価ではない） | 新規: `tests/test_postgres_memory_migration.py::test_synthetic_protocol_corpus_not_model_quality` |
| `test_stale_rebuild_does_not_send_or_starve_current_work` | 2 | limit1/16で旧設定jobをfailed化し後続を処理、旧承認の出典を送らない | 新規: `tests/test_postgres_memory_migration.py::test_stale_rebuild_does_not_send_or_starve_current_work` |
| `test_failed_oldest_job_allows_later_job_and_explicit_retry` | 1 | 先頭job失敗でも後続成功、自動再試行なし、明示extractの新job結果と旧jobを分離 | 新規: `tests/test_postgres_memory_migration.py::test_failed_oldest_job_allows_later_job_and_explicit_retry` |
| `test_mixed_fact_and_instruction_is_framed_as_historical_data` | 1 | 命令混在本文はuserの非信頼データframeへ、systemに混入せず一時参照/出典epochと削除guard保持 | 新規: `tests/test_postgres_memory_migration.py::test_mixed_fact_and_instruction_is_framed_as_historical_data` |
| `test_late_failed_attempt_cannot_retire_or_commit_explicit_retry` | 1 | 古いfail/commitは後続jobへ作用せず、doneに遅延failしても結果保持 | 既存: `tests/test_postgres_stores.py::test_failed_attempt_cannot_retire_or_commit_successor` |
| `test_optional_memory_denial_allows_local_history_without_lookup` | 6 | private有無×permission/機微/判定不能の拒否で検索なし、local会話と履歴保存継続 | 新規: `tests/test_postgres_memory_migration.py::test_optional_memory_denial_allows_local_history_without_lookup` |
| `test_denied_query_with_mutation_is_not_optional` | 3 | query拒否中のpolicy/scope/classifier ABAは認可変更として送信拒否 | 新規: `tests/test_postgres_memory_migration.py::test_denied_query_with_mutation_is_not_optional` |
| `test_unexpected_memory_storage_error_propagates` | 1 | CoreError以外の保存障害は伝播、provider送信・revision更新・receiptなし | 新規: `tests/test_postgres_memory_migration.py::test_unexpected_memory_storage_error_propagates` |
| `test_memory_search_errors_allow_memoryless_conversation` | 10 | storage/結果拒否/出典無効/version/provenance×JSON/SSEで記憶なし継続、query/本文/例外はログなし | 新規: `tests/test_postgres_memory_migration.py::test_memory_search_errors_allow_memoryless_conversation` |
| `test_failed_memory_context_rechecks_same_prepared_authorization` | 4 | 検索障害時の空contextもpolicy/scope/classifier/owner変更を送信前に拒否 | 新規: `tests/test_postgres_memory_migration.py::test_failed_memory_context_rechecks_same_prepared_authorization` |
| `test_failed_search_keeps_final_payload_privacy_check` | 4 | JSON/SSE検索障害後も最終payload拒否/policy変更で送信・保存なし、例外/traceback/ログに秘密なし | 新規: `tests/test_postgres_memory_migration.py::test_failed_search_keeps_final_payload_privacy_check` |
| `test_failed_search_keeps_history_consent_check_after_inference` | 1 | 検索障害後の推論中に履歴同意撤回した場合、履歴/receiptを保存しない | 新規: `tests/test_postgres_memory_migration.py::test_failed_search_keeps_history_consent_check_after_inference` |
| `test_direct_storage_search_error_still_propagates` | 1 | 直接の記憶検索ではstorage_unavailableを会話用空contextへ変換しない | 新規: `tests/test_postgres_memory_migration.py::test_direct_storage_search_error_still_propagates` |
| `test_empty_memory_context_retains_dispatch_guard` | 3 | 検索permissionなしの空contextもscope/policy/classifier変更で送信拒否 | 新規: `tests/test_postgres_memory_migration.py::test_empty_memory_context_retains_dispatch_guard` |
| `test_rebuild_approval_binds_managed_destination` | 4 | classifier/extractor×endpoint/profile変更は旧jobを送信前failed化、明示extractだけ再承認しversionsを保存 | 新規: `tests/test_postgres_memory_migration.py::test_rebuild_approval_binds_managed_destination` |
| `test_same_destination_identity_reopen_and_normalized_noop` | 1 | 同値URLの正規化と再openでversions不変、残存出典を1回だけ再構築 | 新規: `tests/test_postgres_memory_migration.py::test_same_destination_identity_reopen_and_normalized_noop` |
| `test_legacy_job_without_destination_is_not_implicitly_upgraded` | 1 | 承認先欠落jobを補完せずfailedのまま保存、明示extractも旧jobを書換えない | 新規: `tests/test_postgres_memory_migration.py::test_legacy_job_without_destination_is_not_implicitly_upgraded` |
| `test_destination_changes_during_extraction_prevent_commit` | 2 | classifier/extractorの承認先がawait中に変わった場合に採用拒否・pending保持 | 新規: `tests/test_postgres_memory_migration.py::test_destination_changes_during_extraction_prevent_commit` |
| `test_destination_identity_is_whitelisted_and_secret_free` | 2 | 送信先provenanceの許可field/正規化、秘密field不在、userinfo/query/fragment拒否 | 保存に依存しないためプロセス内のまま（既存it1 markerを保持） |

### `test_semantic_memory.py`

| SQLite側の試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験または理由 |
| --- | ---: | --- | --- |
| `test_opt_in_synonym_ranking_preserves_memory_and_source_provenance` | 1 | 意味検索opt-in、出典/provenance/versions保持、未抽出履歴はembeddingなし、archive/再open後も毎回再計算 | 新規: `tests/test_postgres_semantic_migration.py::test_opt_in_synonym_ranking_preserves_memory_and_source_provenance` |
| `test_equal_relevance_prefers_latest_user_mention_over_newer_memory` | 1 | 同等帯では記憶作成順より出典の最新言及順を優先 | 既存: `tests/test_postgres_semantic_memory.py::test_postgres_equal_relevance_prefers_latest_user_mention` |
| `test_semantic_search_returns_at_most_poc_max_retrieved` | 1 | 7候補でも既定/limit16は最大5件、limit2は2件 | 新規: `tests/test_postgres_semantic_migration.py::test_semantic_search_returns_at_most_poc_max_retrieved` |
| `test_revocation_and_rebuild_never_reembed_withdrawn_source` | 2 | private→解除/削除後も旧出典のembeddingなし、残る出典だけ新IDへ再構築 | 新規: `tests/test_postgres_semantic_migration.py::test_revocation_and_rebuild_never_reembed_withdrawn_source` |
| `test_ineligible_history_is_never_promoted_by_semantic_search` | 2 | 明示除外/private中の履歴は解除後も非適格で抽出・embeddingなし | 新規: `tests/test_postgres_semantic_migration.py::test_ineligible_history_is_never_promoted_by_semantic_search` |
| `test_semantic_candidates_never_cross_any_binding_axis` | 4 | subject/client/audience/character各軸で他Bindingの候補をembeddingしない | 既存: `tests/test_postgres_semantic_memory.py::test_semantic_search_never_embeds_another_postgres_scope` |
| `test_changes_during_await_fail_closed`（stage=candidate_authorization、全9変更） | 9 | 候補認可/embedding await中の撤回・policy・classifier・encoder世代/space・scope・store変更はfail-closed | 新規: `tests/test_postgres_semantic_migration.py::test_changes_during_await_fail_closed` |
| `test_changes_during_await_fail_closed`（stage=embedding、private/delete/policy/classifier/mutated_space/scope） | 6 | 候補認可/embedding await中の撤回・policy・classifier・encoder世代/space・scope・store変更はfail-closed | 新規: `tests/test_postgres_semantic_migration.py::test_changes_during_await_fail_closed` |
| `test_changes_during_await_fail_closed`（stage=embedding、store/embedding/space） | 3 | 候補認可/embedding await中の撤回・policy・classifier・encoder世代/space・scope・store変更はfail-closed | 既存: `tests/test_postgres_semantic_memory.py::test_postgres_search_rechecks_storage_and_embedding_generation_after_await`（change=store/generation/space） |
| `test_embedding_failure_is_bounded_content_free_and_never_optional` | 4 | 直接検索の例外/timeout/cancel/不正vectorを内容なしで拒否しcancel伝播 | 新規: `tests/test_postgres_semantic_migration.py::test_embedding_failure_is_bounded_content_free_and_never_optional` |
| `test_embedding_failure_allows_memoryless_conversation` | 8 | JSON/SSE×例外/timeout/不正vector/metadataで記憶なし会話、query/本文/例外のログなし | 新規: `tests/test_postgres_semantic_migration.py::test_embedding_failure_allows_memoryless_conversation` |
| `test_conversation_cancel_during_embedding_propagates_without_append` | 1 | 会話embedding中cancelは閉鎖/伝播しprovider・履歴・receiptなし | 新規: `tests/test_postgres_semantic_migration.py::test_conversation_cancel_during_embedding_propagates_without_append` |
| `test_invalid_search_rejected_before_classifier_or_embedding` | 5 | query空/過大・limit0/17/boolはclassifier/embedding前に拒否 | 新規: `tests/test_postgres_semantic_migration.py::test_invalid_search_rejected_before_classifier_or_embedding` |
| `test_denied_content_and_oversize_scope_never_reach_embedding` | 5 | query/候補認可/permission/本文byte budget/1000件超はembedding前に拒否 | 新規: `tests/test_postgres_semantic_migration.py::test_denied_content_and_oversize_scope_never_reach_embedding` |
| `test_semantic_context_retains_dispatch_guard_and_stateless_compatibility` | 6 | 空/非空×private/encoder/space変更のdispatch guard、statelessはembeddingせず出典frame保持 | 新規: `tests/test_postgres_semantic_migration.py::test_semantic_context_retains_dispatch_guard_and_stateless_compatibility` |
| `test_broken_embedding_metadata_is_content_free` | 1 | 不正metadata例外を内容なしmemory_embedding_failedへ変換 | 新規: `tests/test_postgres_semantic_migration.py::test_broken_embedding_metadata_is_content_free` |
| `test_nonselected_source_revoked_during_result_authorization_rejects_search` | 1 | 結果に選ばれなかった候補の出典撤回も最終認可で拒否 | 新規: `tests/test_postgres_semantic_migration.py::test_nonselected_source_revoked_during_result_authorization_rejects_search` |
| `test_semantic_revocation_during_dispatch_classification_never_calls_provider` | 2 | JSON/SSE最終payload分類中の撤回でproviderを呼ばない | 既存: `tests/test_postgres_semantic_memory.py::test_revocation_after_context_assembly_prevents_model_dispatch` |

### `test_memory_confirmation.py`

| SQLite側の試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験または理由 |
| --- | ---: | --- | --- |
| `test_refusal_signal_identifies_each_user_source_without_content` | 4 | JSON/SSE×日英拒否語の各user出典を本文なし信号で識別、履歴保持・形成保留 | 既存: `tests/test_postgres_memory_confirmation.py::test_refusal_signal_identifies_each_user_source_without_content` |
| `test_refusal_signal_guides_user_selected_turn_and_whole_history_deletion` | 2 | JSON/SSE確認信号の会話全体/選択往復/以降削除のmethod・path・scope、履歴の自動削除なし | 新規: `tests/test_postgres_memory_confirmation_migration.py::test_refusal_signal_guides_user_selected_turn_and_whole_history_deletion` |
| `test_assistant_refusal_quotes_and_history_do_not_hold_new_user` | 12 | JSON/SSE×assistant発話/引用/否定/過去拒否語で現在userを誤保留しない | 既存: `tests/test_postgres_memory_confirmation.py::test_assistant_refusal_quotes_and_history_do_not_hold_new_user` |
| `test_tool_refusal_text_does_not_create_confirmation` | 1 | toolの拒否語はuser確認を作らない | 既存: `tests/test_postgres_memory_confirmation.py::test_tool_refusal_text_does_not_create_confirmation` |
| `test_unanswered_source_is_rejected_before_extraction` | 1 | 未回答の保留sourceは抽出前拒否しextractorを呼ばない | 既存: `tests/test_postgres_memory_confirmation.py::test_unanswered_source_is_rejected_before_extraction` |
| `test_decline_releases_only_target_and_preserves_explicit_exclusion` | 1 | 拒否回答は対象の保留だけ解除し別保留・明示除外を保持 | 既存: `tests/test_postgres_memory_confirmation.py::test_decline_releases_only_target_and_preserves_explicit_exclusion` |
| `test_accept_erases_existing_memory_and_never_restores_accepted_source` | 1 | 受入でprivate化と既存記憶の即時消去、解除しても旧記憶/受入発話は復活しない | 既存: `tests/test_postgres_memory_confirmation.py::test_accept_erases_existing_memory_and_never_restores_accepted_source` |
| `test_stale_and_repeated_confirmation_leave_state_unchanged` | 1 | stale/repeated回答は状態を変えない | 既存: `tests/test_postgres_memory_confirmation.py::test_stale_and_repeated_confirmation_leave_state_unchanged` |
| `test_confirmation_obeys_history_policy` | 1 | 確認操作は履歴permissionを必要とする | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_obeys_history_policy` |
| `test_confirmation_cannot_change_another_binding` | 1 | 別Bindingの確認操作で状態変更なし | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_cannot_change_another_binding` |
| `test_decline_does_not_disable_private_mode` | 1 | 拒否回答で既存privateを解除しない | 既存: `tests/test_postgres_memory_confirmation.py::test_decline_does_not_disable_private_mode` |
| `test_confirmation_invalidates_inflight_completion` | 1 | 確認回答は進行中推論を失効させappendしない | 既存: `tests/test_postgres_memory_confirmation.py::test_confirmation_invalidates_inflight_completion` |
| `test_resolved_confirmation_retry_keeps_receipt_dates_and_does_not_rehold` | 1 | 解決済み同一request再送は元receipt/日時を返し再保留しない | 既存: `tests/test_postgres_memory_confirmation.py::test_resolved_confirmation_retry_keeps_receipt_dates_and_does_not_rehold` |
| `test_pending_confirmation_and_receipt_survive_sqlite_restart` | 1 | 再open後も保留source拒否・snapshot/receipt保持、再送でprovider呼出しなし | 既存: `tests/test_postgres_memory_confirmation.py::test_pending_confirmation_and_receipt_survive_postgres_restart` |
| `test_sqlite_accept_rollback_preserves_memory_and_allows_retry` | 1 | private受入途中の本文消去失敗で履歴/記憶/通知をrollbackし再試行可能 | 既存: `tests/test_postgres_memory_confirmation.py::test_postgres_accept_rollback_preserves_memory_and_allows_retry` |
| `test_pending_source_is_not_current_for_memory_commit` | 1 | 保留SourceVersionはcommit前のcurrent照合を通らない | 既存: `tests/test_postgres_memory_confirmation.py::test_pending_source_is_not_current_for_memory_commit` |
| `test_sqlite_v4_migration_keeps_old_dates_receipts_and_does_not_scan_history` | 2 | 日時NULL/既存日時の旧schema移行で本文・出典・epoch・receiptを保持し過去拒否語を再scanしない | 既存: `tests/test_postgres_memory_confirmation.py::test_postgres_v2_migration_keeps_old_dates_receipts_and_does_not_scan_history` |

### `test_memory_context_refs.py`

| SQLite側の試験 | ケース数 | 検証する契約 | PostgreSQL側の対応試験または理由 |
| --- | ---: | --- | --- |
| `test_generated_identifier_collision_preserves_content_policy_and_guard` | 8 | local/external×conversation/memory×電話/カード形UUIDの衝突でも公開ID保持、一時参照化、user本文は拒否、削除guard維持 | 新規: `tests/test_postgres_memory_context_refs.py::test_generated_identifier_collision_preserves_content_policy_and_guard` |
| `test_context_references_preserve_shared_source_relationships` | 1 | 共有出典の一時conversation参照は同じ関係を保ち、本文・revision/index/epochと記憶参照を保持 | 新規: `tests/test_postgres_memory_context_refs.py::test_context_references_preserve_shared_source_relationships` |

### 保存方式に応じた境界の置換

- adapter再openは、同じschema設定からPostgresDatabase/PostgresMemoryを再構築します。
- SQLiteのraw SQL検査は同じBindingのPostgreSQL transactionとpsycopgへ置換しました。
  本文NULL・状態・job数・versions・旧job状態などのassertionは維持します。
- 秘密のSQLiteファイルbyte検査は、PostgreSQL schema内の全表の論理行にその合成文字列が
  保存されていないことへ置換しました。WAL・旧tuple・物理媒体の検査は追加しません。
  SQLiteファイルのbyte表現だけに依存するassertionを、PostgreSQLの物理消去保証へ広げません。
- outboxのSQLite subprocess強制終了は、該当するSQL中断点にPostgreSQL triggerで例外を注入し、
  transaction rollback・処理済み状態・job登録・再試行の契約を検証します。
  本文消去の中断は既存試験、job登録/通知更新の中断だけ新規試験としました。
  注入関数を削除してからadapterを再openし、厳格なschema検証を保ちます。
- 旧承認先欠落job試験のSQLite user_version=6確認は、PostgreSQL schema version=5の確認へ置換しました。
  job versions/stateが変更されない契約は維持します。

## TDDの実測

1. 起点で `uv sync --frozen` と `pytest -m postgres --collect-only -q` を実行し244件を確認。
2. 新規試験を書き、harnessのsetupを未実装にした状態で、接続設定なしの直接pytestを実行。
   `test_extract_restore_search_archive_and_retry` の2ケースと共有参照の1ケースが計3 ERROR。
   全て必須DSC_TEST_POSTGRES設定の欠落で失敗し、SKIPは0件。
3. `PYTEST_ADDOPTS='-k test_extract_restore_search_archive_and_retry' bash tools/test-postgres.sh`
   を実行。実PostgreSQL fixture/schemaを作成後、harness未接続のNotImplementedErrorで2 FAIL。
   これは試験用harnessのREDであり、既存adapterの契約欠陥を発見した結果ではありません。
4. 製品コードを変えず、setupをPostgresHistory/PostgresMemoryへ接続。新規初期152件と既存244件の
   全396件がPASS（0 SKIP）。SQLiteへfallbackするharnessは作っていません。
5. 案内2件・outbox2件を加えた初回は398 PASS / 2 FAIL。障害注入関数があるまま再openして
   厳格schema検証に拒否された試験側の問題でした。注入関数を除去してから再openする順に修正。
   製品のschema検証を緩めず、最終ゲートで全400件PASS（0 FAIL、0 SKIP）を確認。
6. PostgreSQL保存経路の負の対照として、試験用harnessにだけ一時的にmemories INSERT拒否triggerを
   注入し、手順3と同じ2ケースを再実行。PostgreSQLからのstorage_unavailableで2 FAIL（終了1）。
   注入コードを元のファイルへ完全復元して再実行すると2 PASS（終了0）。
   復元ファイルは全400件PASS時とbyte一致を確認しました。製品コードのmutationはしていません。
   この一時trigger/注入コードは最終変更に含めません。

## 品質ゲート

| コマンド | 結果 | 件数・範囲 |
| --- | --- | --- |
| `uv sync --frozen` | PASS | lock固定、78パッケージ導入（editable Coreを含む） |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS | Python 94ファイル |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS | 94ファイル |
| `uv run --no-sync mypy` | PASS | 94ファイル、0 issues |
| `uv run --no-sync pytest -m ut -q` | PASS | 477件、0 FAIL、0 SKIP |
| `uv run --no-sync pytest -m it1 -q` | PASS | 863件、0 FAIL、0 SKIP |
| `uv build --no-build-isolation` | PASS | sdist/wheelの2成果物 |
| `bash tools/test-postgres.sh` | PASS | 400件、0 FAIL、0 SKIP（移植前244件） |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS | 23件、0 FAIL、0 SKIP/TODO/cancel |
| `node tools/check-docs.mjs` | PASS | 追跡text・Markdown参照・JSON、1ゲート |
| `git diff --check` | PASS | 新規7ファイルの差分、1ゲート |

通常UT/IT1はsocket禁止、postgres試験は専用Unix socket許可の既存pytest設定で実行しました。
既存のStarlette/AnyIOとPydanticの非失敗警告は残ります。
初回のFAIL/ERROR、意図的な負の対照のFAILを、この最終PASS件数へ足していません。

## 確認事項・範囲外

現時点でPostgreSQL adapterの修正を要する契約欠陥は観測していません。
実LLM、実モデル品質、実環境IT2/ST、公開CI、CodeRabbitはNOT RUNです。
ローカルの合成試験結果をこれらのPASSへ読み替えません。
既存SQLite試験の削除は#88、公開操作は監督担当です。
