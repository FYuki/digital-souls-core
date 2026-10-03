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
逐次token配送ではありません。完了前の切断・キャンセル・例外では新しいturnは残りません。
保存完了後に配送が途切れた場合は同じ本文とrequest IDで再試行してください。
stream値も再試行fingerprintに含みます。復旧時に切り替えないでください。

policy欠落・判定不能・拒否は403、不明会話は404、上限超過は413、不正上流応答は502です。
保存失敗は成功やDONEとして返しません。エラー本文へ入力・秘密値を反映しません。
削除は進行中推論を自動キャンセルしませんが、その後の保存を拒否します。

第2段階のpolicyには保存前、復元、送信前、完了後の再確認があります。削除はpolicy撤回後にも
使えます。第3段階の記憶抽出・検索はなく、保存した履歴を同一会話で直接再利用するのみです。
