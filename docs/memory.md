# 明示的な記憶抽出と参照検索

ローカル単一利用者向けのStage3最小実装です。起動時の既定は引き続き未接続・拒否です。
稼働サービスのhistoryを有効化したり、私的会話を自動取り込みするものではありません。
[ADR 0007](adr/0007-memory-provenance-and-revocation.md)を参照してください。

## 接続と操作

trusted Python起動コードで、履歴と同じSQLiteファイルを使う`SQLiteMemory`、同じ`PrivacyPolicy`、
検証済みlocal Profileを持つ`LocalClassifier`/`LocalExtractor`を構成します。
memoryのHTTP操作やscope自己申告fieldは追加しません。利用者のsubject/client/audience/characterは
`Binding`に固定されます。別Bindingのsource・job・memory・通知を照合できません。

```python
from digital_souls_core.local_extractor import LocalExtractor
from digital_souls_core.memory import MemoryContext, MemoryService
from digital_souls_core.sqlite_memory import SQLiteMemory

# policy/classifier、provider、local_profile、inferenceはtrusted起動側で固定済み。
# historyとmemoryの同一DB・同一policyを保つ。実サービスへ自動適用しない。
store = SQLiteMemory()
memory = MemoryService(
    store, policy,
    LocalExtractor(provider, local_profile, model_digest="operator-pinned-model-digest"),
)
inference.memory_context = MemoryContext(memory)
# create_app(inference, history_store=store, history_policy=policy)
# 明示sourceを選んだ時だけ await memory.extract(binding, source_refs)
# await memory.search(binding, "mint")
# await memory.rebuild(binding, limit=16)  # 有限batch。常駐workerではない。
```

抽出にはlocal/memory permissionが必要です。保存済み履歴のuser発話だけをsourceにできます。
source条件と現行privacyを通っても、LLM候補が不正なら採用しません。assistant/tool発話は採用しません。
履歴保存の許可だけでは記憶抽出は始まりません。既存stateless APIはmemory contextを検索しません。
conversation経路で接続を明示した場合だけ、通常ContextSourceに加えてGuardedContextSourceを取得します。

## episode/semanticの最小契約

モデル出力は`schema_version=memory-v1`、候補型、`basis=explicit_user_statement`とsource indexだけです。
余分/欠落field、未知型、重複key/index、範囲外index、tool call、途中終了、内部思考は拒否します。
候補本文をモデルに生成させず、指定されたuser発話全体をCoreがJSON配列へ変換して保存します。
言い換え・抜粋による否定の脱落や、存在しない日時/主体の生成を保存経路で防ぎます。
episodeは出来事のuser report、semanticは事実/嗜好のuser reportの分類ラベルです。
正規化した時刻schemaや検証済みuser factへ昇格させる機能はありません。人格/Loreを書き換えません。

分類器・抽出器は既存Provider portの固定`llamacpp_chat` loopback経路だけを使用し、外部fallbackはありません。
scannerはsource、query、候補、provenanceを永続化/モデル送信の前に検査します。
意味分類と抽出はそれぞれ最大15秒（profileが短ければその値）。失敗/timeoutは内容なしのエラー、
cancelは伝播し、未完jobを残して明示再試行できます。複数callを伴う操作全体は15秒ではありません。
実モデルの選択精度・機微分類精度は未検証です。合成corpusでmockした選択を検証する試験と、
実モデルの生成品質評価を区別します。promptだけを品質保証の強制機構とは扱いません。

## source失効と削除・再構成

SQLite schema v3へ原子的に移行し、v1/v2の履歴・receiptを保持します。
private化はconversationのmemory epochを進め、履歴を保持しつつ派生memory本文を同一transactionでNULL化します。
履歴削除も派生本文を同一transactionで消します。text index/cacheを別途保持しないため、そこからの復活はありません。
ID・source refs・epoch・versionの最小tombstoneは残り、旧IDをactiveへ戻しません。
private解除は旧epochを復活させません。private中に記録したturnも非適格のままです。
将来の明示新規抽出は現在の適格性・epoch・privacyを再判定し、別IDを生成します。

内容なし`memory_events`は既存SourceDeletionと別のdurable outboxです。旧通知をprivate化に流用しません。
`consume`は残存する元epochのsourceだけでrebuild jobを永続登録してから処理済みにします。
consumer停止中も旧本文は既に消えており検索できません。job作成後にさらにsourceが撤回された場合も
残る適格sourceへ絞り直し、古いjobをobsoleteにします。解除された撤回sourceをそのjobへ戻しません。
再構成は旧本文を読まず、残存履歴だけを再抽出します。成功まで代替memoryを返しません。
根拠ゼロなら再構成せず、失敗時も旧本文/IDを復活させません。通知処理・job採用は冪等です。
再構築jobは元の承認済み設定を維持します。設定不一致や処理失敗（CoreError）はjobを failed へ
終端化し、同じbatchの後続jobを続行します。batch終了後は内容なしの memory_rebuild_incomplete
エラーを返します。失敗jobは次回の自動対象外で、limit=1でも後続が永久に詰まりません。
旧設定の出典を新profileへ自動送信しません。再試行には利用者が現在の出典を明示して extract
を呼び、現在の適格性・privacy・設定で再承認します。同設定の再試行もこの明示経路のみ別job IDで作成します。失敗job自体は再開しません。
旧試行の遅延fail/commitは新試行へ作用せず、並行する明示再試行は同じ後続IDを共有します。
同一source・設定の連続失敗は128試行で上限エラーとし、無制限の探索を避けます。
キャンセルは終端化せず伝播し、DB障害等の予期しない例外も隠しません。
DB transactionをLLM await中に保持しません。採用時にsource epoch・設定generationを再照合します。

## 検索と送信境界

検索はcasefold後の部分文字列一致で、最新作成順です。意味検索・embedding・語彙展開・ランキング学習はありません。
queryは1〜256文字、limitは1〜16件、1 Bindingのactive memoryが1000件を超える場合は413で拒否します。
各memoryの全sourceを照合するため、計算量は対象memory数と出典数に比例します。速度の実測保証はありません。
全質問文を部分一致queryにすると一致しにくいため、Python検索では特徴的な短い語句を明示します。
conversation自動contextは最新user文の先頭256文字をqueryにし、最大4件を既存context byte budget内で扱います。
抽出は最大16 source（各2048文字）、最大8候補です。過大なcontextは切り捨てず既存のbudget errorにします。

文字列化後もmemory ID・source refs/epochsを内部guardが保持します。現在のpolicy owner/generationとsourceを
取得前・各await後・推論dispatch直前に照合します。通常ContextSourceや分類器のawait中のpolicy交換・
source撤回では外部providerを呼びません。呼び出し開始済みの通信は回収できません。
archiveは一覧表示だけで、memory検索の条件を変えません。

## 現在の範囲外

私的input import、実モデル品質評価、正規化時刻、自由要約、過去発話への後付け除外/訂正API、
memory単体の編集UI、vector検索、常駐job、tombstone自動掃除、ファイル/バックアップの物理消去保証は対象外です。
合成fixtureとfake transportでの成功を、これらの完了や実品質の合格とは扱いません。


記憶本文は人格systemメッセージへ結合せず、独立した user role の retrieved_memory_data として
過去の出典データを渡します。systemには、命令として実行せず人格・system指示を上書きしない
という固定の扱いだけを記載します。JSONにはmemory ID・種別・原文・source revision/epochを保持します。
これは命令と事実が混在する記憶への緩和策で、実モデルでのprompt injection完全防御を保証しません。
privacy再判定・source guard・context byte budgetは、このframeを含む送信payloadに引き続き適用します。


## 会話時の記憶なし継続

会話contextでmemory許可がない場合、記憶storeを参照せず通常の推論認可へ進みます。
queryの記憶利用が拒否された場合（機微判定・ABSTAIN・分類器の判定不能を含む）も、
検索前にpolicy/設定/呼び出しscopeが不変と確認できた場合だけ空contextへ戻します。
専用の MemoryQueryUnavailable 型（code: memory_query_unavailable）で区別し、一般のCoreErrorは吸収しません。
直接の記憶検索APIはこの拒否をエラーとして返します。結果の拒否、source撤回、設定不正、
policy変更、storage障害、キャンセルは会話でもfail-closedです。
空contextでも送信前まで呼び出しscope・policy世代・設定のguardを保持します。
分類器の代入は単調増加する世代を更新し、交換後に元のobjectへ戻しても古い判定を再利用しません。


## 承認済み処理先の識別

classifier/extractor双方のprovenanceには、model/digestに加えて transport・profile ID・
正規化したloopback endpoint・識別形式のversionを保存します。http scheme、127.0.0.1、
数値port、固定/v1 pathから組み立て、URLの同値な表記差は同じidentityとします。
profile IDだけの変更も別の承認先と扱います。token/key/headerは保存せず、
userinfo/query/fragmentを含むURLは既存のProfile検証で拒否します。
これは運用者が固定した設定の識別であり、endpoint背後の実プロセスやmodel digestの真正性保証ではありません。

既存SQLite v3のversions JSONを拡張するため、DDL migrationや旧行の書き換えはありません。
送信先識別を欠く旧jobは新設定と一致せず、再構築時には本文を取り出す前に拒否され、
既存のfailed終端化・後続処理へ進みます。現在のendpointを旧承認へ補完しません。
旧active memoryの出典検証・検索と履歴データは維持しますが、再構築・抽出jobを再利用する際には
現在のsource適格性とprivacyを満たす明示extractが必要です。
既存v1/v2→v3 migrationとoutboxの原子性は変更せず、crash回帰も継続します。
