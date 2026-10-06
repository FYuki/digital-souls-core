# アーキテクチャ決定記録（ADR）

ファイル名は`NNNN-short-title.md`とし、Status（Proposed / Accepted / Superseded）、
日付、背景、選択肢、決定、影響、関連Issue・PR・証跡のリンクを記載します。
Acceptedにする際はレビューでの決定を参照してください。
履歴を黙って書き換えず、新しい記録で以前の決定を置き換えます。
今回の初期整備では、製品アーキテクチャの決定は承認していません。

- [ADR 0004: 明示的な会話履歴の永続化](0004-conversation-history.md)
- [ADR 0008: 管理された分類器・抽出器の構造化出力](0008-managed-structured-output.md)
- [ADR 0009: モデル向け記憶contextの一時参照名](0009-memory-context-references.md)
- [ADR 0010: 明示注入したプロセス内embeddingによる記憶検索](0010-in-process-memory-search.md)
- [ADR 0011: 固定SDKによる明示的なローカルembedding接続](0011-local-memory-embedding.md)
- [ADR 0012: 明示選択するPostgreSQL履歴・記憶backend](0012-postgresql-storage.md)

記憶モデルはPoCの採用済み決定を移設して再編しました（ADR 0015〜0020）。
機能の実装状況と受入条件は[SPEC](../../SPEC.md)、用語は[CONTEXT](../../CONTEXT.md)を参照してください。

- [ADR 0015: PoCの記憶モデル決定の移設と再編](0015-memory-model-reorganization.md)
- [ADR 0016: 記憶の種別・正本・日時](0016-memory-kinds-and-records.md)
- [ADR 0017: 記憶の形成と保存判定](0017-memory-formation-admission.md)
- [ADR 0018: 記憶の検索と会話での利用](0018-memory-retrieval-context.md)
- [ADR 0019: 記憶の訂正・時間変化・矛盾・削除と失効](0019-memory-correction-invalidation.md)
- [ADR 0020: 内省・人格・関係・生活状態と記憶の接続](0020-reflection-personality-relationship.md)
