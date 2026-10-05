# ADR 0013: 独立したpgvector派生記憶indexのPoC

Status: Proposed

日付: 2026-10-05

## 背景と1000件上限の意味

[ADR 0007](0007-memory-provenance-and-revocation.md)は、由来を持つ記憶と同一transactionでの
撤回・本文消去を定め、派生indexを持たない語句検索から始めました。
[ADR 0010](0010-in-process-memory-search.md)は、候補全体を再認可して検索中だけvectorを
計算する方式を追加しました。既存の検索境界は維持します。

1000件はDBの保存容量ではなく、1 Bindingのactive memoryを全件読む検索経路のhard limitです。
SQLiteとPostgreSQLの `_memories()` は最大1001行を読み、1000行を超える場合は413で拒否します。
この数はsourceの適格性判定より前のactive行数です。記憶のcommit自体には1000件を上限とする
容量検査はありません。MemoryStore Protocolが全backendへ課す保存容量とも定義していません。

意味検索側には、1000候補と候補本文UTF-8合計256 KiBの追加検査があります。
根拠は全候補の再認可・source再確認・一時vector計算を有限にすることであり、
「1000件を超えるとDBが遅くなる」という性能実測から選んだ値ではありません。
既存の偽embedding試験は上限超過をembedding前に拒否することを確認します。
pgvectorの評価だけでこの上限や通常起動の保存設定を変更しません。

## 選択肢と決定

既存方式の上限だけを引き上げる案、現行PostgreSQL schemaへ直ちにvector列を追加する案、
独立した合成データ用schemaで派生indexの契約を検証する案を比較し、最後の案を選びます。

`experiments/pgvector_memory/` にPoCを閉じ込め、本番 `src/` のschema、
PostgresDatabaseの厳格なschema検証、MemoryService、PrivacyPolicy、dispatch guardを変更しません。
独立schemaのsource・memory projectionをこのPoC内の正本とし、実履歴を読み込まず、
明示的に生成した合成データだけを渡します。本番履歴の代わりとなる製品APIではありません。
ここでprivate・除外を操作する試験は、合成source snapshotを不適格にする試験です。
実conversationのprivate変更を全turn/messageへ伝播させる同期は実装せず、その成功を主張しません。

現行PostgreSQLの撤回処理には、派生indexへ呼び出すtransaction内hookがありません。
固定schemaは未知のrelation/function/triggerを拒否します。そのため独立PoCの成功を、
既存history/memory adapterへ透過的に接続できた証拠とは扱いません。
将来の結線にはsource mutationと派生無効化を同じtransactionへ置く変更と、
そのschema互換性の別レビューが必要です。

## 派生データの識別

`PgvectorMemoryStore(PocConfig, EmbeddingSpace)` をtrustedな実験コードから明示構築します。
既存Bindingのsubject/client/audience/characterをすべてキーに含めます。

| 情報 | 役割 |
| --- | --- |
| Bindingとmemory ID | 公開範囲と対象記憶の識別 |
| memory revisionと本文hash | 本文・出典を更新した旧結果の失効 |
| source ID・SourceReference相当の参照と採用時epoch | conversation/turn/messageと撤回世代の照合 |
| index generationとstatus | 遅延完了・重複・再試行による旧vector復活の防止 |
| model/revision/dimensions/configuration | 同じembedding spaceだけを照合 |
| 永続space generation | 設定変更から元設定へ戻る場合も古い結果を拒否 |
| vector | 上記の値に従属し、消去・再生成できる派生データ |

memory revisionはPoC projection側の単調なversionです。既存の `Memory` 契約へfieldを
追加しません。本文hashは内容一致の検査であり、匿名化や保存同意の代用ではありません。
source情報は合成sourceの明示的なconversation ID・turn revision・message indexとepochを維持します。
非ゼロmessage indexや複数turnを便宜上0へ潰さず、memoryから別memoryへ出典を付け替えません。embedding設定は検索側の識別として保持し、抽出jobのprovenanceと混ぜません。

## 変更・撤回と生成完了の境界

1. sourceの変更・除外・private化・削除は、関連memoryのrevisionとindex generationを進め、
   旧memory本文とvectorを同じtransactionで消去してinvalidにします。本文hashも空本文のhashへ
   置き換えます。source projection自体は本文を持たないmetadataです。private解除だけでは復活しません。
2. 明示的なmemory追加・本文更新・再構成はrevisionとgenerationを更新し、旧vectorを消して
   pendingにします。複数sourceの一部失効では旧本文/vectorを返さず、残る適格sourceだけを使う
   明示的な再構成を要求します。invalid/deletedの旧IDをpendingへ戻さず、再構成には新しいIDを使います。
   同IDの本文更新はready/pendingの記憶に限定します。
3. memory削除は本文消去、deleted状態、派生vector消去を一度に確定します。scope移動は
   旧Binding側をtombstoneにし、対象Bindingの適格sourceを検証した新しいpending対象を作ります。
   移動先に同IDのinvalid/deleted tombstoneがあれば再利用を拒否します。
4. `prepare()` が取得したWorkItemは本文・source snapshot・revision・hash・世代・spaceを固定します。
   embedding計算中はDB transactionを保持しません。PoCは合成vectorを使い実モデルを呼びません。
5. `complete(work, vector)` は同じtransaction内で全snapshotを再照合するCASです。
   不一致、失効、削除、scope変更、space変更後の完了は採用しません。readyへ戻すために
   古いgenerationを再利用しません。
6. `set_space()` によるspace変更は永続space generationを進め、旧派生vectorを全消去します。
   以前と同じmodel名へ戻しても古いWorkItemや検索tokenは再有効化しません。

PoCはschema単位のadvisory transaction lockでread/writeを直列化します。
これは競合時の正しさを小さく検証するための制約で、複数Bindingの高並行性能を示す構成ではありません。
消去の確認対象は可視SQL状態と検索結果です。WAL・backupを含む物理媒体からの消去はこのPoCの検証範囲外です。

## 検索とdispatch直前検証

まずexact cosine検索を使います。SQLはBinding、active/ready状態、memoryのversion/hash、
全sourceの現在適格性とepoch、embedding space/generationを満たす行を対象に順位付けします。
別scopeの近傍を取得してからアプリ側だけで取り除く方式にしません。
正のcosineのみを返し、同点は作成順の新しいものを先にします。同じIDの本文更新では作成順を変えません。
検索入力は合成query vectorで、結果limitはPoC専用の1〜1000です。既存APIのquery文字数やlimitを変更しません。

`SearchHit.token` は本文から分離した照合情報を持ち、`valid(token)` で検索後の変更を確認できます。
将来MemoryContextへ接続する場合、query事前認可、結果本文の再認可、既存policy・検索設定stamp、
token有効性を各await後と推論dispatch直前にすべて照合します。
空結果でも既存の設定・policy guardを落としてはいけません。

このPoCはPrivacyPolicyの分類器を呼ばず、MemoryServiceや最終推論へも接続しません。
`valid(token)` の成功だけで本文の送信許可を与えることはできません。
既存のquery事前拒否だけを任意の記憶なし継続とする契約も変更しません。

## 検索形式と依存

pgvector 0.8.7の固定sourceを参照し、コンテナもdigestで固定します。
PoCのvectorはfloat32、dimensionsは1〜2000とします。既存EmbeddingSpaceの1〜4096とは
別の実験上の制約であり、本番契約を狭める変更ではありません。
非有限値、ゼロvector、次元不一致、float32変換後の不正値を拒否します。
要素が有限でもfloat32のnorm計算がoverflow・zero underflowするvectorはこのPoCでは拒否し、
正規化によって入力を黙って置き換えません。

pgvectorの既定はexact検索であり、ANN indexの追加は速度とrecallのtradeoffを伴います。
vector型の格納上限とHNSW/IVFFlatの次元上限も同一ではありません。
本PoCではHNSWを既定で使わず、必要ならexactの結果を基準に独立した評価を行います。
根拠は[固定した公式README](https://github.com/pgvector/pgvector/blob/f37c13f68b57d2c3472b2214fbcff699d6d34876/README.md)です。

## 受入条件と未検証範囲

- 合成データで全Binding軸の分離、private/指定source除外/削除、複数sourceの部分失効、
  scope移動、本文更新、モデル・revision・次元・設定変更を検証します。
- 生成中の各変更、完了の重複と順序逆転、削除後の遅延完了、transaction途中失敗により、
  古い本文/vectorやready状態が復活しないことを確認します。
- 検索直後の変更はtokenを失効させます。検索結果に元memory ID/source情報を保持し、
  非ゼロmessage index・複数turnの出典も損失なく照合します。
- 同じfloat32入力に対するPython exact順位付けとSQLの結果を比較し、正cosine、同点、
  空結果、数値誤差、異常vectorを区別します。
- 100/1000/10000件の合成比較では生成・投入・更新・検索・転送・Python順位付け・容量を分けます。
  10000件はPoC primitiveの評価であり、既存MemoryServiceを通る試験ではありません。
- 実embeddingの精度・時間、実履歴、実GPU、本番サービス、既存DB移行、scheduler、運用配備は対象外です。
  未実行項目をPASSにせず、合成試験をモデル品質の証拠としません。

関連Issue: [#48](https://github.com/FYuki/digital-souls-core/issues/48)。
実行方法と計測の読み方は[pgvector PoC](../pgvector-poc.md)に記載します。
