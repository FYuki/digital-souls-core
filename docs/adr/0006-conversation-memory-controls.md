# ADR 0006: 履歴と長期記憶の明示的な操作境界

Status: Proposed

日付: 2026-10-03

## ユーザーが指定した操作仕様

| 操作 | 会話履歴 | 長期記憶 |
|---|---|---|
| 通常 | 保持 | 対象 |
| 記録しないで（指定発話） | 保持 | 対象外 |
| プライベートモード（スレッド単位） | 保持 | 対象外 |
| 会話履歴削除 | 削除 | そこから作られた記憶も削除 |
| アーカイブ | 一覧で非表示 | 維持 |

この表は[ADR 0005](0005-privacy-boundaries.md)の自然言語保存拒否に関する仮案に優先します。
secret/機微検査・外部送信許可は別です。操作によって秘密値の保存・送信を許可しません。
長期記憶の抽出・採用・検索本体は未実装なので、「対象」は必要なsource条件を表します。

## 決定案

自然文から期間・スレッド設定を推測しません。UI/Agentが明示APIで指定します。
completionの`memory_excluded_indices`で今回の入力配列内の発話を選びます。
指定された発話は通常どおり履歴へ保存し、元データを変更せず記憶sourceの対象外とします。
返答は除外発話に依存し得るため、そのassistantも対象外です。以後のassistant/toolも同じ履歴を
参照する限り対象外を維持します。新しい独立user発話は明示除外されなければ対象候補です。

threadの`private_mode`と`archived`はPATCHで変更し、期待revisionによる排他を用います。
private中に保存したturnは解除後も自動で対象へ戻しません。現在privateのthreadは全sourceを利用不可とします。
これは実装上の保守的なsource gateであり、既存の派生memoryを物理削除する実装ではありません。
archiveは通常一覧から隠すだけで、直接復元・source eligibility・削除は引き続き可能です。

sourceはtrusted Bindingと、conversation ID・turn revision・message indexで識別します。
復元APIはmessage順にsource参照と現在のeligibilityを返します。source条件の通過だけで
privacyや根拠・候補型の審査を省略できません。Stage3は採用時・取得時に再検証します。

会話削除と内容を含まない`SourceDeletion`通知を同じSQLite transactionで確定します。
削除後はsourceの照合が即時falseになるため、通知の処理待ちを理由に古いsourceを有効としません。
通知はscope・characterで分離し、trusted consumerが派生memory/indexの削除後にacknowledgeします。
HTTPに通知ack操作を公開しません。通知は本文を含まず、stage3 consumer未接続中は保持します。
同じ会話の再削除は通知を増やしません。未知IDや別scopeの削除にも通知を作りません。

SQLite schema v1→v2はALTERと通知table作成を単一transactionで実行します。
既存の履歴・receipt・fingerprintを保持し、新しい除外fieldが空の場合は旧request fingerprintを維持します。
control変更もconversation revisionを進め、進行中の旧revision推論はcommitできません。

## 代替案と影響

- 自然語から保存範囲を推定する方式は「指定発話」を越えて適用し得るため採用しません。
- archiveをdeleteで表現する方式は記憶sourceを失うため採用しません。
- メモリ削除を同期callbackだけで伝える方式は停止中の通知を失うため、永続通知にします。
- 生成応答の厳密な依存解析は未実装なので、過去の除外内容を参照し得るassistant/toolを保守的に除外します。
  除外を含む会話で生成された安全な独立応答も対象外になり得ます。
- 過去発話への後付け訂正・除外変更、通知の自動consumer、memory/index実削除はこの実装に含めません。

## Stage3前の判断点

1. private切替時、既に形成済みの過去memoryを物理削除するか、private中だけ利用停止するか。
   この段階はsource利用停止までで、過去memoryの削除動作を確定しません。
2. 複数sourceで統合したmemoryで一つのsourceが削除された場合、全体を削除するか、残る根拠から再形成するか。
   fixture consumerは削除通知の受渡しだけを検証し、製品の統合記憶ルールを確定しません。

## 参照

- [履歴API](../history-api.md)
- [privacy境界](../privacy.md)
- [第1段階ADR](0004-conversation-history.md)
