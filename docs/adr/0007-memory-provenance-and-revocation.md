# ADR 0007: 出典を持つ最小記憶と撤回・再構成

Status: Proposed

日付: 2026-10-03

## 確定した要求と適用順序

[ADR 0006](0006-conversation-memory-controls.md)の2つの製品判断はユーザー承認済みです。
private化はthread由来memoryを削除し、複数sourceの一部が消えた/対象外になった場合は旧memoryを
即時利用停止して、残る適格sourceだけから再構成します。旧memoryは成功まで返さず、private解除で
自動復活しません。ここから下のschema・実装構成はStage3着手前の提案です。

privacy → controlsの順でmainのCI・実CodeRabbit review・承認済みmerge gateを完了してから実装します。
この文書は私的実会話の取り込み、実データ削除、実推論/GPU操作を許可しません。
実classifierの品質は未検証のままです。人格品質の人手評価は実装進行の停止条件にしません。

## 現行契約との整合と不足

| 現行 | Stage3で必要な扱い |
|---|---|
| Binding＋conversation/turn/messageのsource参照 | 同じ識別子を維持し、全memory/source/jobをBindingで分離 |
| source_eligible | 必要条件として維持。memory状態・撤回世代・現行privacyも照合 |
| private PATCHのrevision CAS | 同一transactionで撤回世代を進め、内容なし撤回通知を追加 |
| SourceDeletion | 履歴消去通知として維持。private化で履歴が消えたとは通知しない |
| durable deletion outbox＋ack | 冪等consumerと再構成jobを追加。ackの完了条件を明文化 |
| archive | 検索対象を変えず、通常会話一覧だけから隠す |

現在のprivate切替には通知がなく、on→offがconsumer停止中に起きるとbooleanだけでは撤回を失います。
conversation単位の永続的なmemory epochを追加し、private化時に単調増加させます。
memory採用時のsource epochを保持し、異なるepochの旧memoryを解除後も無効にします。
履歴削除ではsource不存在が無効化条件です。過去発話の後付け除外APIは現時点の範囲外ですが、
将来追加するときも同じ撤回経路が必要です。現行の発言指定は新しい入力だけが対象です。

## 最小保存モデル（提案）

既存SQLiteを使用し、新しいDBサービス・vector DB・embedding依存を導入しません。
memoryはhistoryと同じtransactionを利用できるadapterに置き、内側にはstorage非依存portを定義します。
新規schema migrationは既存履歴/receiptを保持し、crash/rollbackを検証します。
既定のGit外保存領域と権限を引き継ぎ、memory本文・候補・indexをログへ出しません。

- memory: ID、Binding、型（episode/semantic）、検証済本文、state、作成時刻、抽出器/モデル/
  prompt/schema/policy version。性格設定・Loreを書き換えません。
- memory_source: memory IDと元のSourceReference、採用時epoch。出典は元履歴へ直接結び、
  初期実装ではmemoryから別memoryを形成する連鎖を許しません。
- revocation: event ID、Binding、source範囲、理由、epoch。本文を含めず永続化。
- extraction/rebuild job: 冪等key、対象source参照、設定version、状態。旧memory本文を再構成入力にしません。
- 旧memoryは本文/indexを削除し、必要最小限のID・撤回世代・job関係だけをtombstoneとして残します。
  成功した再構成は別IDを採番し、旧IDをactiveへ戻しません。

## 明示抽出と型

trusted callerがBindingと明示source集合・固定profileを指定して有限のbatch処理を実行します。
自動履歴取り込み、常駐worker、scheduler、Core内tool実行ループは追加しません。
既存Provider portを使い、local抽出を初期構成とします。local/memory permission、決定論的検査と
意味分類を通ったsourceだけを入力にし、外部fallbackをしません。
不適格sourceを含む過去会話全体を便宜的なcontextとして渡しません。

episodeは根拠のある出来事と明示された時間を持ち、未知の時間・主体を推測しません。
semanticは明示された事実/嗜好などの候補とし、assistantの提案を利用者の事実へ変換しません。
各候補に根拠sourceを必須とし、曖昧・矛盾・根拠不明なら採用しません。
最初は少数のstrict schemaで欠落/追加field、型、長さ、件数、source集合外参照を拒否します。
内部思考や秘密値を出力schemaに持たず、応答は採用前にも秘密/機微・根拠・source条件を検査します。
推論中はDB transactionを保持せず、採用transactionでsource/epoch/設定generationを再照合します。
再試行はBinding・source参照集合・source epoch vector・設定versionのjob keyで重複採用を防ぎます。
private解除後の明示新規抽出は更新されたepochで区別します。rebuild keyには撤回event IDと旧memory IDも
含め、異なる撤回事由を同じjobへ潰しません。

## 撤回と再構成

private化/履歴削除は同一transactionでsource状態・epoch・通知を確定します。
全取得経路は状態と現在source/epochを照合し、consumerが止まっていても旧memoryを返しません。
キャッシュだけで許可せず、候補採用とcontext組立時にも再確認します。既に送信済みの内容は回収できません。

consumerは対象旧memoryの利用停止、本文/indexの削除、残る出典の再構成job登録を原子的に確定します。
単一sourceまたは適格sourceがゼロなら再構成しません。複数sourceで根拠が残るときだけjobを作ります。
履歴を消す/対象外にしたsourceはjob入力から除き、旧memory本文を再利用しません。
privateが解除されても、その撤回eventが除いたsourceを同じrebuildへ戻しません。
将来の明示新規抽出は、その時点の適格性・epoch・privacyを改めて判定します。

ackは旧本文/indexの除去と必要jobの永続登録が成功した後に行います。
再構成LLMの成功待ちはack条件にせず、失敗/timeout/cancel時も旧memoryは削除状態を維持します。
consumerの再配信・重複・順序逆転に耐え、より新しい撤回を古い処理で上書きしません。
再構成の採用直前にも全残存sourceを検証し、途中撤回された候補を採用しません。

## 検索とcontext

初期検索はSQLite内の決定的な語句検索と件数/長さ上限に絞ります。高度な意味検索は後続です。
source joinとstate/epoch/Binding/現行privacyの条件を通るmemoryだけを順位付け・返却します。
削除済indexの残存、別character/scope、stale cacheを取得結果へ出しません。
既存ContextSourceの接続口を使い、予算内でmemory ID・出典付きcontextを組み立てます。
sessionを明示しない既存stateless APIへ暗黙の履歴保存や自動記憶取得を追加しません。
現行ContextSourceの文字列返却だけでは、context組立後の分類器await中に起きた撤回を照合できません。
source参照・epoch・memory IDを本文と共に内部で保持する接続口を追加し、送信直前境界へ渡して再検証します。
このmetadataをモデル入力へそのまま公開する必要はありません。返却/送信時のpolicy取消とsource撤回を
別々に検証し、最後のawait後に撤回済みcontextが送られない競合試験を追加します。

## 受入試験と段階

1. 合成memory repository・scope・順序・再試行・migrationを先に検証。
2. private on→off/consumer停止、delete、通知重複/順序逆転、ack前後crashを検証。
   即時取得拒否、本文/index削除、旧ID非復活、残存sourceだけのrebuildを確認。
3. fake Providerでepisode/semanticのstrict schema、根拠、秘密、timeout/cancel、不正応答、
   推論中のsource撤回、policy世代変更を検証。LLM await中にDB transactionを保持しない。
4. 検索/contextの別Binding混線、archive、stale cache、採用直前/送信直前撤回を検証。
5. 必須lint/type/UT/IT/docs/build/install・独立差分レビュー・CI・CodeRabbit gateを通す。

全て合成データから始めます。実classifier品質・実抽出品質の評価は別途明示された実環境作業で行い、
未検証を成功と扱いません。private input importの許可は引き続きありません。
