# 意味検索・回答評価の固定ケース

合成のみ。実会話・私的ログ・認証情報は含めません。決定は [ADR 0023](../../docs/adr/0023-semantic-evaluation-contract.md)、本番契約は [ADR 0022](../../docs/adr/0022-memory-retrieval-from-records.md)です。

## 分類と件数

| category | 件数 |
| --- | --- |
| synonym | 10 |
| paraphrase | 10 |
| cross_language | 10 |
| unrelated | 10 |
| negation | 1 |
| update | 1 |
| multisource | 1 |
| multisource_revocation | 1 |
| private | 1 |
| excluded | 1 |
| deleted_source | 1 |
| deleted_memory | 1 |
| binding_character | 1 |
| binding_subject | 1 |
| binding_client | 1 |
| long_text | 1 |
| after_search | 1 |
| after_answer | 1 |
| epoch_change | 1 |
| fact_attachment | 1 |
| fact_version | 1 |
| fact_revocation | 1 |
| semantic_direct | 1 |
| semantic_derived | 1 |
| equivalent_order | 1 |
| threshold | 1 |

合計 **62件**。モデル依存4分類は各10件です。

## 旧ケースとの対応

旧 PR #51 head `5a573e2` のケース名を `legacy_id` に保持します。本文は `normalized_text` に移し、会話履歴は合成し直します。旧sourceのrevision/indexは新しいappend可能な会話へ対応付け直しています。

| legacy_id | 新case id | 移行上の差分 |
| --- | --- | --- |
| synonym-warm-drink-ja | synonym-warm-drink-ja | 本番のEpisode/citationへ変換。 |
| paraphrase-weekend-ja | paraphrase-weekend-ja | 本番のEpisode/citationへ変換。 |
| cross-language-herb | cross-language-herb | 本番のEpisode/citationへ変換。 |
| unrelated-observatory | unrelated-observatory | 本番のEpisode/citationへ変換。 |
| negated-coffee-preference | negated-coffee-preference | 本番のEpisode/citationへ変換。 |
| updated-morning-drink | updated-morning-drink | 旧本文はFact版1。版2と新リンクをregisterし、Episodeへ現行Factを添付。 |
| multisource-picnic | multisource-picnic | 本番のEpisode/citationへ変換。 |
| multisource-partial-revocation | multisource-partial-revocation | 会話単位privateでは残存出典も失効するため、撤回側の往復だけ削除。残存Episodeは事前登録済みで再生成ではない。 |
| private-source | private-source | 本番のEpisode/citationへ変換。 |
| excluded-source | excluded-source | 後付け除外APIはないためappend時の除外。対象記録は登録拒否probe。 |
| deleted-source | deleted-source | 本番のEpisode/citationへ変換。 |
| deleted-memory | deleted-memory | 記憶だけの直接削除APIはないため出典の選択往復削除で本文を消去。 |
| binding-character | binding-character | 本番のEpisode/citationへ変換。 |
| binding-subject | binding-subject | 本番のEpisode/citationへ変換。 |
| binding-client | binding-client | 本番のEpisode/citationへ変換。 |
| long-text-explicit-detail | long-text-explicit-detail | 本番のEpisode/citationへ変換。 |
| post-search-revocation | post-search-revocation | 本番のEpisode/citationへ変換。 |
| post-answer-revocation | post-answer-revocation | dispatch前は有効。応答後の再検証で回答を破棄する期待。 |
| source-epoch-changed | source-epoch-changed | epochの直接書換えはしない。private化→解除で世代を進め、旧記録の自動復活を拒否。 |

`unsupported-public-audience`（分類 `unsupported_audience`）は移しません。現行 `AccessScope.audience` は `local-private` 固定であり、`public` を表現できません。型外のBindingを捏造しません。

## ファイルと利用API

- [cases.json](cases.json)：query、検索Binding、合成会話と記録、操作手順、偽vector。goldを含めません。分類もgold側だけに置きます。
- [expectations.json](expectations.json)：分類、検索候補の `relevant_ids` / `forbidden_ids`、該当なし、期待順、添付Fact ID、dispatch直前のguard、回答の必須語句・禁止語句・挙動と破棄の期待。
- [semantic_evaluation_cases.py](../../src/digital_souls_core/semantic_evaluation_cases.py)：`load_evaluation_cases(cases_path, expectations_path)` / `parse_evaluation_cases(cases_json, expectations_json)` が分離した型と相互検証結果を返します。DB・推論は使いません。各記録の `to_domain()`、citationの `citation()`、`registration_batches(case)`、Fact更新mutationの `batch()` を後続で使えます。

初期記録は版1・ACTIVE。新Fact版は `expected_version` の直後の版で登録します。Factは検索候補ではなく添付で採点し、`required_fact_ids` / `forbidden_fact_ids` を使います。同じFact IDの更新内容は回答の必須・禁止語句で区別します。

### 後続ハーネスの実行順

1. ケース単位で隔離し、各Bindingで `HistoryStore.create` を使います。fixtureの会話IDは論理名なので生成IDへ写像し、履歴・citation・EpisodeEvidenceのsourceも一緒に置換します。
2. 会話のuser/assistant対をturn_revision順に `append` します。message_indexはturn内0始まりです。`stated_at` はtrusted clockから保持します。`exclude_on_append` は **この段階** で `memory_excluded_indices` へ渡します。後付け更新はしません。
3. `registration_batches` が返すBindingごとのbatchを `MemoryRecordStore.register` します。除外出典を引用する記録はbatchから外し、別の登録試行が拒否されることも確認します（その記録のdomain変換自体は可能）。
4. `before_search` の残る操作を配列順に実行します。`set_private` は `controls`、`delete_turn` は `delete_turns(scope="selected")`、`delete_conversation` は `delete`。expected_revisionは現snapshotから取得します。`update_fact` は `batch()` とそのBindingで `register`。新リンクは新IDで登録します。SQLによるsource/epoch変更は禁止です。
5. 本番設定の `MemoryRetrieval` で検索し、本番 `MemoryContext` のcontextを生成します。検索返却時の候補IDと添付Factをgoldと比較します。`after_search` はcontext取得後・dispatch前、`after_answer` は回答生成後・公開前に実行し、その時点のguardを再検証します。

`dispatch.valid` はdispatch **直前** の期待です。after_answerではtrueであり、応答後の失効は `answer.discarded` で表します。guard無効時は送信/公開を拒否します。検索が正常0件なら有効な空contextで `no_memory` とし、架空の事実を補いません。`no_match` は検索時点の期待で、必須ゲートは閾値以上の適格候補0件です。

### 偽embeddingと品質評価

queryと全normalized_text（Fact各版を含む）には共通4次元の有限・非ゼロvectorがあります。同一本文は全ケースで同じvectorです。queryと候補をunit vectorにし、二乗L2距離から `relevance = 1/(1+sqrt(distance))` を計算します。本番の候補20・閾値0.54・同等帯0.002・最大5を使います。Factのvectorは本文対応の完全性用で、Factを独立候補にしません。

偽vectorはCIで道具を検証するためのものです。**モデルの品質証拠ではありません**。実モデル評価は手動・cacheなし3回、各回各分類90%以上、必須ゲート全件合格で判定します。平均で相殺せず、結果に合わせて期待値・閾値を緩めません。

回答goldの `required_facts` は全語句を含み、`forbidden_facts` は全語句が不在であることを要求します。出典の表記は採点しません。日英ケースではqueryと異なる言語の必須語句も維持し、回答プロンプトが記憶の語句を保持できるかを評価します。入力へgoldを注入しません。
