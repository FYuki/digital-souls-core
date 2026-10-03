# 会話履歴API（第1段階）

通常の`create_app()`と既存`/v1/chat/completions`、`/v1/character/completions`はstatelessです。
履歴保存・復元は[ADR 0004](adr/0004-conversation-history.md)の明示的な別経路です。

## 有効化と信頼境界

組込み利用者が`create_app(inference, history_store=store, history_policy=policy)`へ
HistoryStoreと信頼されたHistoryPolicyを注入します。SQLite実装は
`digital_souls_core.sqlite_history.SQLiteHistory`です。policyなしでは全操作を既定拒否しますが、
同じscopeの削除は可能です。HTTPからpolicyを設定したり、安全と自己申告したりする機能はありません。
単一のローカル利用者がloopback上で使用します。既存Host/Origin境界を適用します。

第1段階に本番用保存policyはありません。合成テスト以外の私的実会話を自動取り込みしないでください。
第2段階で秘密・機微情報の判定を導入するまでは、この境界を安全と判断した本番運用は行いません。

## 経路

共通prefixは`/v1/characters/{character_id}/conversations`です。

| Method | Path | 動作 |
| --- | --- | --- |
| POST | prefix | 空の会話を作成し201。本文は不要 |
| GET | prefix | このcharacter/scopeの`conversation_ids`を作成順に取得 |
| GET | prefix/{conversation_id} | `conversation_id`・`revision`・順序付き`messages`を復元 |
| DELETE | prefix/{conversation_id} | 会話と全turn/receiptを削除。存在しないIDにも204 |
| POST | prefix/{conversation_id}/completions | 新規入力を追加して推論し、完了した往復を原子的保存 |

completion本文の例（合成データ）:

```json
{
  "request_id": "synthetic-turn-1",
  "expected_revision": 0,
  "messages": [{"role": "user", "content": "合成テストの挨拶"}],
  "stream": false
}
```

`messages`には新しいuserまたはtoolのみを渡します。過去ログを再送しません。
tools/tool_choice/temperature/max_tokens/max_completion_tokensの条件は既存APIと同じです。
request_idは1〜64文字の英数字・`_`・`-`、期待revisionは0以上の整数です。
成功は`conversation_id`、`request_id`、確定`revision`、公開assistant `message`、
`finish_reason`（stop/tool_calls）を返します。OpenAIのresponse envelopeとは異なります。

tool_callsを受け取ったら外部Agentが実行し、次のrequest IDで対応する全tool resultを渡します。
Coreは実行しません。不正な往復は400です。入力・設定が同じrequest IDの再送は同じreceiptを返し、
再推論しません。異なる入力のID再利用、期待revisionのずれは409です。
同時要求は推論コストが重複し得ます。409後は復元して次の入力を判断してください。

## streamと失敗

`stream: true`は上流streamをバッファし、完了・policy許可・commit後に
SSEの`event: completed`（dataは上記成功オブジェクト）と`data: [DONE]`を返します。
逐次token配送ではありません。provider完了後、保存直前にcancelの受付点を設けます。
ASGIの`http.disconnect`をそこで観測済みなら保存せず、SQLite commit区間はawaitなしで実行します。
実際のネットワーク切断時刻とASGI通知の到着時刻は同一とは限りません。
commit後に到着した通知や配送失敗では保存済みreceiptが残ります。
保存完了後に配送が途切れた場合は同じ本文とrequest IDで再試行してください。
stream値も再試行fingerprintに含みます。復旧時に切り替えないでください。

policy欠落・判定不能・拒否は403、不明会話は404、上限超過は413、不正上流応答は502です。
保存失敗は成功やDONEとして返しません。エラー本文へ入力・秘密値を反映しません。
削除は進行中推論を自動キャンセルしませんが、その後の保存を拒否します。

第2段階のpolicyには保存前、復元、送信前、完了後の再確認があります。削除はpolicy撤回後にも
使えます。第3段階の記憶抽出・検索はなく、保存した履歴を同一会話で直接再利用するのみです。


## 同時再試行と初回DB作成

同一requestの同時推論で別の応答が得られても、先に保存したreceiptを維持します。
後から完了した要求も、実際に返す先行receiptを現在のread policyで再確認します。
許可が撤回されていれば403とし、保存済みの内容を別の応答へ書き換えません。

初回schemaのDDLとversion設定は単一transactionです。初期化途中にprocessが終了しても、
SQLiteのrollback後に再初期化できます。未知のversion 0 DBや旧実装で残った部分schemaは
自動修復・削除せず拒否します。既存データを識別せず上書きする移行は行いません。


## 明示的な記憶対象とthread操作

[ADR 0006](adr/0006-conversation-memory-controls.md)の操作表を適用します。
completionに`memory_excluded_indices: [0]`を渡すと、今回の`messages`内のindex 0を
履歴に保存したまま記憶対象外にします。indexは0始まりで重複・範囲外を拒否します。
省略時は空配列で、旧receipt fingerprint互換を維持します。再送で指定を変えると409です。
このmetadataはモデルへ送信しません。自然文だけから指定期間や操作を推測しません。

`PATCH /v1/characters/{character_id}/conversations/{conversation_id}`へ
`{"expected_revision": 1, "private_mode": true}`または`{"expected_revision": 1, "archived": true}`を渡します。
両fieldの同時指定も可能です。少なくとも一方が必要で、revision不一致は409です。
変更もrevisionを進めるため、旧revisionで進行中の推論は保存できません。
通信失敗後はGETで現在の状態を確認してください。PATCHにrequest IDによるreceiptはありません。

通常一覧はarchiveを除外します。`?include_archived=true`で含められます。
archive中もID指定のGET・DELETEと記憶sourceの有効性は維持します。
private中は全sourceを利用不可にし、その間に保存したturnは解除後も自動採用しません。
除外履歴に依存し得る後続assistant/toolも対象外です。新user発話は明示指定に従います。

GETレスポンスには`private_mode`、`archived`、message順の`memory_sources`を追加します。
各sourceは`turn_revision`、そのturn内の`message_index`、`eligible`を持ちます。
conversation IDとtrusted scope/characterと組み合わせて参照します。現在のconversation revisionと
過去のturn revisionは異なり得ます。eligibleはsource条件だけで、privacyや候補採用の許可ではありません。

DELETEは本文・receiptを消し、内容なしのsource削除通知を同じtransactionで残します。
Stage3 consumer用Python portの`deletions(binding)`と`acknowledge_deletion(binding,event_id)`で処理します。
scope違いの通知は取得・ackできません。通知のHTTP ackは公開しません。
同じSQLite v3にある派生memory本文も同一transactionで消去します。再構成の完了とは別です。
source参照自体は削除直後から無効です。

schema v1/v2からv3へ原子的に移行します。履歴・receiptは保持し、未知versionは引き続き拒否します。
過去発話への後付け除外変更は未実装で、指定はcompletionの入力配列に対して行います。


### Stage3の撤回処理

private化は、そのthread由来の既存memoryを削除する製品仕様として承認済みです。
複数sourceの旧memoryは直ちに利用停止し、残る適格sourceのみから再構成が成功するまで返しません。
解除による旧memoryの自動復活は行いません。PATCHはepoch更新・派生本文消去・別のmemory撤回通知を
原子的に確定します。明示batch再構成と制約は[記憶API説明](memory.md)を参照してください。
