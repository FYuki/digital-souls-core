# 明示的な記憶抽出と参照検索

ローカル単一利用者向けのStage3最小実装です。起動時の既定は引き続き未接続・拒否です。
稼働サービスのhistoryを有効化したり、私的会話を自動取り込みするものではありません。
[ADR 0007](adr/0007-memory-provenance-and-revocation.md)を参照してください。

## 接続と操作

trusted Python起動コードで、履歴と同じ保存先のMemoryStore、同じ`PrivacyPolicy`、
検証済みlocal Profileを持つ`LocalClassifier`/`LocalExtractor`を構成します。
保存先は`SQLiteMemory`、または明示選択の[PostgreSQL backend](postgresql.md)です。
[意味検索との統合例](semantic-postgresql-integration.md)でも、接続と記憶抽出は明示操作です。
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

[往復単位の削除](history-api.md#往復単位の明示削除)では、最終的な削除対象のturn revisionを
`memory_sources`のBinding・会話・revisionと照合し、該当出典を持つactive memoryだけを撤回します。
旧本文のNULL化と内容なし`memory_events`の登録は履歴削除と同一transactionです。
会話全体のmemory epochは進めず、他の往復だけを出典にする記憶は保持します。
削除出典はturn行の不存在により、抽出・採用・検索・取得済みcontextの送信直前でも無効になります。
同じPreparedや抽出taskが削除をまたいでも、旧出典の利用・採用を拒否します。

既存consumerは複数出典の旧記憶を残る適格な出典だけで再構成します。旧本文や旧IDは復活させず、
job作成後の追加削除も実行前・採用前に再検証します。再構成が失敗しても旧本文は消えたままです。
対象外の後続往復と削除後に追加したuser往復は、既存のprivacy・private・明示除外・確認状態を
満たせば新しく抽出できます。privateや保留の解除を削除操作から推測しません。
往復通知のoutboxはSourceDeletionと別であり、記憶再構成の既存`memory_events` consumerへも接続します。

SQLiteの`user_version`は、既存v1〜v5から必要な段階を経てv6へ同一transactionで原子的に移行し、履歴・receiptを保持します。
v2でprivate・除外・archiveと`source_deletions`、v3でmemory epoch・記憶tableを追加します。
v4で`turns.stated_at`、v5で`turns.memory_confirmation`（既定値`{}`）、
v6で`turn_tombstones`・`turn_deletions`を追加します。v3以前の旧turnの`stated_at`はNULLのまま補完しません。
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

既定の検索はcasefold後の部分文字列一致で、最新作成順です。全質問文を部分一致queryにすると
一致しにくいため、Python検索では特徴的な短い語句を明示します。語彙展開・ランキング学習はありません。
queryは1〜256文字、limitは1〜16件、1 Bindingのactive memoryが1000件を超える場合は413で拒否します。
limitを省略した場合と意味検索の上限は、下記`RetrievalPolicy`の最大取得件数（既定5件）です。
各memoryの全sourceを照合するため、計算量は対象memory数と出典数に比例します。速度の実測保証はありません。
conversation自動contextは最新user文の先頭256文字をqueryにし、最大取得件数（既定5件）を既存context byte budget内で扱います。
抽出は最大16 source（各2048文字）、最大8候補です。過大なcontextは切り捨てず既存のbudget errorにします。

trusted起動コードが`MemoryService(..., embedding=trusted_embedder)`を明示すると、意味検索を使えます。
`memory_ranking.py`の`MemoryEmbedding` Protocolを実装し、変更不可の
`EmbeddingSpace(model, revision, dimensions)`で処理設定を示します。dimensionsは1〜4096です。
任意の`configuration`は既定値`in-process`で、ローカルadapterでは通信設定も含めます。
既存の接続例では引数を省略しているため、部分文字列検索を維持します。
[ADR 0010](adr/0010-in-process-memory-search.md)のプロセス内portに加え、
[ADR 0011](adr/0011-local-memory-embedding.md)で明示的なloopback通信adapterを提供します。
モデルは同梱せず、任意の注入実装の通信をsandboxで制限する仕組みではありません。

意味検索はquery認可後に、同じBindingで全sourceが現在も適格な候補を取得します。
全候補本文のUTF-8合計が256 KiBを超える場合は、分類器・embeddingへ渡す前に拒否します。
候補本文全体を現在のprivacyで認可し、全候補のsourceと設定を再照合してから、queryと全候補を
1 batchでembeddingへ渡します。候補がない場合はembeddingを呼びません。embeddingのawaitは最大15秒で、
検索操作全体の上限時間を示すものではありません。完了後にも全候補のsourceと設定を照合します。
順位付けはPoCの[RAG検索](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/app/memory/ranking.py)と
[policy値](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/app/memory/memory_policy.json#L42-L48)に合わせた`RetrievalPolicy`で行います。
単位vector間の二乗L2距離が近い順に候補20件へ絞り、relevance `1 / (1 + sqrt(距離))` が0.54以上の
候補だけを残します。先頭とのrelevance差が0.002以内の候補は同等帯とし、帯の中はユーザーの
最終言及が新しい順、作成が新しい順、memory ID順に並べ、最大5件を返します。
最終言及は出典user発話を含むturnの保存順の最大値で、時刻列ではありません。PoCの
`last_user_mentioned_at`と同じ順序を、schemaを変えずに表します。limit以内の結果を改めて
privacy認可し、sourceと設定を照合して返します。不正vector、timeout、失敗は内容なしのエラー、
cancelは伝播し、部分文字列検索へのfallbackはしません。実モデルの検索品質は未評価です。

vectorは検索呼出し中だけの一時値で、永続index・共有cacheを作りません。返却するMemoryのID・本文・
型・source refs/epochsと保存済み抽出provenanceは維持します。private化・指定発話除外・履歴削除・
Binding分離は既存のsource境界を使い、archiveは検索対象を変えません。

文字列化後もmemory ID・source refs/epochsを内部guardが保持します。現在のpolicy owner/generationとsourceを
取得前・各await後・推論dispatch直前に照合します。embeddingの差し替え世代とspaceも別のguardで保持し、
正常に検索して0件だった空contextにも適用します。検索障害で記憶を破棄した場合は、
下記の会話認可guardを保持します。検索設定は抽出jobの`_versions()`に加えず、既存の抽出承認を変更しません。
通常ContextSourceや分類器のawait中のpolicy交換・source撤回・embedding設定変更では古いcontextを
providerへ送りません。呼び出し開始済みの処理や通信は回収できません。

## ローカルembeddingの明示接続

`LocalEmbeddingProfile`と`LocalEmbedding`は`digital_souls_core.local_embedding`にあります。
[profile例](../examples/embedding.example.json)は`enabled=false`の合成設定で、実モデルや稼働portを
確認した値ではありません。起動時に自動で読み込まれず、既存のhistory/dogfood設定を有効にしません。

```python
from pathlib import Path
from digital_souls_core.local_embedding import LocalEmbedding, LocalEmbeddingProfile

# trusted起動側が既存のstore・policy・extractorを構成済み。
# profile例は無効。承認済みの接続先・alias・digest・次元へ別途設定する。
profile = LocalEmbeddingProfile.model_validate_json(
    Path("examples/embedding.example.json").read_text(encoding="utf-8")
)
if profile.enabled:
    memory = MemoryService(store, policy, extractor, embedding=LocalEmbedding(profile))
```

`api_base`は数値port付きの`http://127.0.0.1:<port>/v1`だけを許可します。
`model`は運用者が固定するembeddingモデルaliasで、返答のmodelも同じ値を要求します。
`model_digest`は確認済みモデルの識別を運用者が固定する値であり、adapterが実ファイルを検証する機能ではありません。
`dimensions`は1〜4096の応答次元数です。互換serverの次元縮約機能を前提にせず、requestには送りません。
`timeout_seconds`は0より大きく15秒以下、`enabled`は既定falseです。無効なadapterを注入した場合も、
部分文字列検索へfallbackせず送信を拒否します。

既存lockの`openai==2.54.0`の`embeddings.with_raw_response.create`を使い、float形式のvectorを要求します。
SDKによる型変換前のJSONを検証し、bool等がfloatへ変換されて受理されることを防ぎます。
入力と応答の件数、model、indexの一意性と範囲、次元、非有限値・ゼロvectorを検証します。
環境変数のproxy・認証情報・organization・projectを使わず、redirect・retry・外部fallbackを無効にします。
`OPENAI_CUSTOM_HEADERS`が非空ならclient構築前に拒否し、環境headerによる認証情報・Hostの上書きを防ぎます。
呼出しごとにclientを閉じ、cancel時もcloseを保護します。本文の意味分類とlocal/memory許可は
`MemoryService`で行うため、adapter単体の呼出しを認可済み検索とは扱いません。

正規化endpoint・profile ID・timeout・enabled・adapter/SDKの識別は`EmbeddingSpace.configuration`へ
含め、検索中とdispatch前のguardに使います。抽出jobの保存済みprovenanceとは別で、DB migrationはありません。
稼働済みの会話用モデルがembeddingへ対応する保証はありません。対応するモデルとpoolingを確認した後の
実測手順は[意味検索評価](memory-evaluation.md)を参照してください。今回の実モデル呼出し・品質評価はNOT RUNです。

## 現在の範囲外

私的input import、実モデル品質評価、正規化時刻、自由要約、過去発話への後付け除外/訂正API、
memory単体の編集UI、モデル取得・GPUの操作・実embedding評価、稼働DBへの適用、永続vector index、常駐job、
tombstone自動掃除、ファイル/バックアップの物理消去保証は対象外です。
合成fixture・fake transport・偽embeddingでの成功を、これらの完了や実品質の合格とは扱いません。


記憶本文は人格systemメッセージへ結合せず、独立した user role の retrieved_memory_data として
過去の出典データを渡します。systemには、命令として実行せず人格・system指示を上書きしない
という固定の扱いだけを記載します。JSONにはcontext内だけの`memory_ref`・`conversation_ref`と種別・原文・source revision/epochを保持します。
保存IDはモデルへ送らず、公開検索結果と内部guardに保持します。参照名はそのcontext内だけで有効で、
別リクエストの参照名や公開APIのIDとは対応しません。[ADR 0009](adr/0009-memory-context-references.md)を参照してください。
これは命令と事実が混在する記憶への緩和策で、実モデルでのprompt injection完全防御を保証しません。
privacy再判定・source guard・context byte budgetは、このframeを含む送信payloadに引き続き適用します。


## 会話時の記憶なし継続

会話contextでmemory許可がない場合、記憶storeを参照せず通常の推論認可へ進みます。
検索準備や検索が `CoreError` で失敗した場合は、記憶を破棄して空contextで会話を続けます。
query拒否（機微判定・ABSTAIN・分類器の判定不能を含む）、結果拒否、検索中のsource撤回、
設定不正、storage障害、embeddingの不正出力・失敗・timeoutもこの対象です。
障害内容は保持・ログ出力せず、query・記憶本文・例外文字列を障害応答や後続例外へ転記しません。
キャンセルと `CoreError` 以外の予期しない例外は従来どおり伝播します。
直接の記憶検索は、query拒否の MemoryQueryUnavailable（code: memory_query_unavailable）を含め、
従来どおりエラーを返します。部分文字列検索へのfallbackは行いません。

障害時の空contextは、検索前のpolicy object・世代と呼び出しscope・context ownerの認可を
送信直前まで保持します。失敗した検索設定や破棄したsourceを再検証して検索障害を再発させません。
会話自体の認可が失効した場合は送信を拒否します。最終payloadのprivacy検査と、
推論後の履歴保存認可・revision検証も維持します。
正常な検索結果（0件を含む）は設定guardを保持し、記憶返却後のsource撤回は送信拒否になります。
返却後の再検証失敗を空contextへ差し替えて送信することはありません。
分類器の代入は単調増加する世代を更新し、交換後に元のobjectへ戻しても古い判定を再利用しません。


## 承認済み処理先の識別

classifier/extractor双方のprovenanceには、model/digestに加えて transport・profile ID・
正規化したloopback endpoint・識別形式のversionを保存します。http scheme、127.0.0.1、
数値port、固定/v1 pathから組み立て、URLの同値な表記差は同じidentityとします。
profile IDだけの変更も別の承認先と扱います。token/key/headerは保存せず、
userinfo/query/fragmentを含むURLは既存のProfile検証で拒否します。
これは運用者が固定した設定の識別であり、endpoint背後の実プロセスやmodel digestの真正性保証ではありません。

送信先識別は既存SQLiteのversions JSONを拡張するため、追加のDDL migrationや旧行の書き換えはありません。
送信先識別を欠く旧jobは新設定と一致せず、再構築時にはclassifier/extractorへ送信する前に拒否され、
既存のfailed終端化・後続処理へ進みます。現在のendpointを旧承認へ補完しません。
旧active memoryの出典検証・検索と履歴データは維持しますが、再構築・抽出jobを再利用する際には
現在のsource適格性とprivacyを満たす明示extractが必要です。
送信先識別の拡張ではschema migrationやoutboxの原子性は変更せず、crash回帰も継続します。
現在のschemaは、上記の段階的migrationでv6へ移行します。


再構築全体での本文取得前拒否は保証しません。runの設定比較より先に、
consume/rebaseの適格性確認が_current/_sourceを通じてSQLite内の本文を読み取って解析します。
今回の境界はモデルへの送信停止であり、このローカル内部読み取りは残ります。

## 管理された構造化出力

分類器・抽出器は固定JSON Schemaをproviderへ渡し、返却値のstrict検証を維持します。未対応・不正出力は拒否し、制約なしの再試行は行いません。schema・対応契約・SDK versionも承認provenanceに含むため、旧承認は自動的に引き継ぎません。[ADR 0008](adr/0008-managed-structured-output.md)を参照してください。

## 記憶の正本のdomain契約

[記憶の種別・正本・日時](adr/0016-memory-kinds-and-records.md)に対応する保存非依存の値型を
`digital_souls_core.memory_records` に定義します。既存の逐語記憶の型・挙動は維持します。
`Episode` は経験の5W・日時・仮定/創作の文脈を持ち、`Fact` は呼出し側が採番した安定IDの内容一版です。
`Episode` / `Fact` の各版は保存文と引用を独立して保持します。
`EpisodeFactLink` は両者のID・版付き参照を持ち、保存文や最終言及日時を持ちません。
`Semantic` は構造化命題と適用時期を持ち、直接抽出はuser引用を必須とします。
経験からの形成は同一Episode IDの出典をまとめ、互いに素な `SourceReference` 集合を持つ
Episodeが2件以上なければ拒否します。元発言のepochや引用範囲の違いは独立性を増やしません。

`Citation` はBinding・既存の `SourceVersion`・話者・message内の半開文字範囲 `[start, end)` を
結び付け、元の本文をコピーしません。5Wは述語を必須とし、不明な項目を補いません。
`ExplicitReason` は明示された理由と引用を持ちます。`PartialDateTime` / `TemporalValue` は
部分日時の精度、単一の点、同じ精度の端点の範囲、不明、解釈時のタイムゾーンを保持します。
月精度で日を埋めず、未知の日時は `TemporalValue()` として明示します。

全記録にID・1以上の整数版・Binding・tz-awareな登録日時・ACTIVE/SUSPENDEDの状態を持たせます。
`Episode` / `Fact` / `Semantic` はさらに非空の保存文とtz-awareな最終言及日時（不明可）を持ちます。
別Bindingの引用・参照や不正な値は生成時に拒否し、本文・構造化内容をreprに出しません。
`RecordRef` と純粋関数
`dependency_invalidated` は、現在の種別・ID・Binding・版・有効状態が一致する場合だけ依存先を
有効と判定します。参照先が存在しない場合や版が一致しない場合も失効です。本文消去後も `RecordHead`（参照と状態だけの値）で判定できます。

これらは構造の契約です。保存portでの出典の現在版・適格性の照合、引用範囲と履歴本文の対応、
Episode出典集合の照合、旧版の保持、撤回時の本文消去、抽出・保存文の生成は後続の実装で扱います。
