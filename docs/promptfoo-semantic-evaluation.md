# promptfoo による意味検索と出典付き回答の評価

この評価は、固定した合成ケースを使い、意味検索と、その検索結果を根拠にした回答を別々に検査します。
実装は独立した `evals/semantic/` に置き、promptfoo **0.117.2** と専用lockfileを固定します。
製品wheel、通常の起動、保存設定、正本の会話履歴を変更しません。
設計は [ADR 0014](adr/0014-promptfoo-semantic-evaluation.md)、
作業範囲は [Issue #50](https://github.com/FYuki/digital-souls-core/issues/50)、
実行結果は [日付付き証跡](evidence/2026-10-05-promptfoo-semantic-evaluation.md) が正本です。

## 評価する境界

provider は [pgvector PoC](pgvector-poc.md) の `PgvectorMemoryStore` を、使い捨てDB内の
ケースごとの独立schemaで実際に操作します。sourceを明示投入し、記憶の追加・更新・削除・
source変更を適用してからexact cosine検索とtoken再確認を行います。
実 `MemoryService`、`MemoryContext`、SQLite、正本の履歴APIを通すE2E試験ではありません。
sourceのprivate・除外フラグは合成projectionです。実threadのprivate変更を全発話へ伝播させた
証拠や、privacy classifierの分類精度として扱いません。

| suite | 入力と検査 | モデル呼出し |
| --- | --- | --- |
| retrieval | query、適格候補、返却ID・順位・由来・公開範囲、検索後のtoken再確認 | fixtureは0回、local-modelはembeddingのみ |
| answer | 同じ検索と、許可された記憶だけによる回答、引用、回答後の再確認 | fixtureは記憶本文を引用付きで連結、local-modelは明示chat profileのみ |

検索直後の撤回は回答生成前に拒否し、回答直後の撤回は生成済み回答を破棄します。
空結果は回答モデルを呼ばず、answer suiteでは根拠なしの定型文を返します。
この制御されたmutation試験はPoC tokenの境界を調べるもので、任意の外部並行更新と
本番dispatchを完全に結線した保証ではありません。

## ケースと正解の分離

[入力cases.json](../evals/semantic/cases.json) は20件の独自合成データです。
[expectations.json](../evals/semantic/expectations.json) はassertionだけが読む正解です。
providerに渡すpromptfoo変数は `case_id` のみです。providerは対応する入力を読み、
モデルへはquery・許可された記憶本文だけを渡し、正解ID・禁止ID・期待する事実を渡しません。
fixture vectorも実モデルへ送信せず、local-model時は明示profileのembeddingで置き換えます。

`expected_sources` はtop-kの正解だけでなく、同じBindingでembeddingへ渡してよい候補全体の
由来を保持します。source ID、revision、epoch、conversation ID、turn revision、
message indexを照合し、非ゼロindexや複数turnを潰しません。
検索前に失効した記憶と別Bindingの記憶は、検索・embedding・dispatch・引用のすべてで禁止します。
検索後に失効する記憶は検索時点の期待IDに残し、後段のtoken失効と送信禁止を別に検査します。
入力にgoldを混ぜないことはコードの参照境界であり、同じOS利用者に対するファイル秘匿機構ではありません。

全ケースの `limit=1` です。fixtureでは4次元の非ゼロvectorを固定し、期待IDを順序込みで
完全一致させます。正解のあるケースは `min_recall=1`、正解がないケースのrecallは
分母0のため `null` です。空結果をrecall 100%へ置き換えません。
現在の20件では複数件の同点順位やtop-kの広い分布を測っていません。

| case ID | 確認する違い・fixtureの期待 |
| --- | --- |
| synonym-warm-drink-ja | 温かい飲み物という質問から紅茶の `tea-preference` を取得 |
| paraphrase-weekend-ja | 休日の運動という言い換えから `weekend-cycle` を取得 |
| cross-language-herb | 英語の質問から日本語の `windowsill-mint` を取得 |
| unrelated-observatory | 天文台の根拠がなく空結果、回答は根拠なし |
| negated-coffee-preference | `coffee-dislike` を取得し「コーヒーが苦手」「飲みません」と引用を要求 |
| updated-morning-drink | 同IDの本文更新後、`morning-drink` のほうじ茶を使い旧緑茶回答を拒否 |
| multisource-picnic | `picnic-items` の2つのsourceと異なるturn/indexを保持 |
| multisource-partial-revocation | 片方のsource撤回で旧複合記憶を禁止し `remaining-food-only` だけを取得 |
| private-source | private化した旧記憶を禁止し `private-source-visible` だけを取得 |
| excluded-source | 指定sourceを除外し `excluded-source-visible` だけを取得 |
| deleted-source | source削除後は `deleted-source-visible` だけを取得 |
| deleted-memory | 記憶削除後は `current-notebook` だけを取得 |
| binding-character | より近い別character候補を禁止し `binding-character-own` だけを取得 |
| binding-subject | より近い別subject候補を禁止し `binding-subject-own` だけを取得 |
| binding-client | より近い別client候補を禁止し `binding-client-own` だけを取得 |
| unsupported-public-audience | 未対応audience `public` をI/O前に入力拒否 |
| long-text-explicit-detail | 長い合成本文の橙色リボンを `long-note-memory` から取得 |
| post-search-revocation | 検索では同名接頭辞の記憶を取得し、直後の撤回で回答生成を禁止 |
| post-answer-revocation | 検索では同名接頭辞の記憶を取得し、回答後の撤回で回答を破棄 |
| source-epoch-changed | source世代更新により旧IDを失効させ空結果 |

Bindingの4軸はsubject/client/audience/characterです。現行Coreのaudienceは
`local-private` のみであり、`public` の分離保存や公開回答を実装したとは扱いません。
private・除外・削除ケースでは、初期状態から `before_search` の変更で失効させます。
`rejected_memory_ids` は初期投入をadapterが拒否したIDだけで、この20件では空です。

## 必須ゲートと品質指標

private、指定発話相当のsource除外、削除、Binding、由来、embedding送信対象、token再検証、
失効後のdispatch・回答破棄は必須ゲートです。平均点や他ケースの正解で失敗を相殺しません。
fixtureのID完全一致、retrievalのrecall、回答の期待句・禁止句・引用は分けて集計します。
report gateは完全なcase集合・provider・suite・結果件数を照合し、0件、欠落、重複、未知ID、
provider error、非有限score、壊れた出力を拒否します。
promptfooの終了コードや集計pass率だけを受入条件にしません。

local-modelでは、実際の取得IDが許可候補内であり、Bindingと完全なsource情報が一致することを
必須にします。dispatch対象は実際の取得IDと失効tokenから決め、1件でも失効していれば
すべて送信しません。正解記憶の検索漏れや空結果は、適格性違反ではなくrecall・回答品質の
失敗です。正解IDが空のケースで何かを取得した場合も検索品質の失敗として記録します。
必要な引用の欠落は品質の失敗、未送信・禁止IDの引用は必須ゲート違反として区別します。

回答の事実検査は、文字列と引用IDによる限定的な検査です。否定ケースでは「コーヒー」だけの
含有で通さず否定句を要求しますが、矛盾する追加文、すべての言い換え、各引用の意味的な支持を
完全には判定しません。実モデルの適切な言い換えもfalse negativeになり得ます。
LLM judgeによる追加呼出しを行わず、文字列検査の成功から包括的な回答品質を主張しません。

fixture vectorは意味の良さを測るためのモデルではありません。
local-modelの検索では無関係な本文も正cosineになる場合があり、現行の `cosine > 0` という
条件で `unrelated-observatory` の空結果が通るとは限りません。
モデルを用意しただけで品質PASSになるわけではなく、失敗したquery・ID・設定・指標を
改善用の証跡として残します。結果に合わせたgoldや閾値の緩和は行わず、仕様変更なら理由と
変更前後をレビューします。どちらのmodeも、この段階の `quality_evidence` は `false` です。

実モデル呼出しのある結果も、包括的なモデル品質は `NOT_ESTABLISHED` と記録します。

## 実行

Nodeはリポジトリ指定の24.19.0、uvは0.8.22です。依存取得時のみネットワークを使います。
promptfooは製品用依存から分離してインストールします。

```sh
uv sync --frozen
npm ci --prefix evals/semantic --ignore-scripts --no-audit --no-fund
bash tools/build-semantic-sqlite.sh
bash tools/evaluate-semantic.sh fixture
```

専用build手順はbetter-sqlite3 11.10.0の同梱sourceと固定Node headersを使い、
network namespace内でnative moduleを作ります。g++とmakeが必要です。

runnerはretrievalとanswerの両suiteを必須実行します。
[pgvector専用runner](../tools/test-pgvector-poc.sh)のdigest固定imageを使い、
ネットワークなし・公開portなしの使い捨てDBへ専用Unix socketで接続します。
fixtureの評価プロセスも別network namespaceへ隔離します。
Nodeからのネットワーク要求を拒否し、環境を清掃してdotenv・資格情報・proxyの継承を防ぎ、
telemetry・update確認・共有・cacheを無効にします。concurrencyは1です。
promptfoo 0.117.2は `--no-write` を指定すると公式JSON exportの `results.results` が空になり、
完全な結果を再検証できません。そのため `--no-write` は使わず、専用一時directory内の
SQLiteへ合成評価結果を保存して公式exportを利用します。正本履歴や本番DBへは書きません。
起動時のSQLite状態・ログ・raw reportと同様、この私有stateは実行後も確認用に保持します。
`--no-cache` と共有無効化は維持し、結果の空配列を成功と見なす緩和は行いません。
必要な隔離機能が使えない場合は失敗にし、通常networkへフォールバックしません。

GitHub hosted Ubuntu 24.04では、一般ユーザーのUID map作成が拒否されるため、
CIだけが明示的な専用起動方式を使います。GitHubの使い捨てVM上で固定system commandが
network namespaceを作成し、元の非root UID/GIDへ戻し、補助group・capabilityを落として
`no-new-privileges`を設定してからbuild・評価を実行します。
rootで評価用のshell、Node、Pythonを実行せず、ホストのsysctlやAppArmor設定も変更しません。
ローカルの既定動作は一般ユーザーによるnamespace作成のままで、sudoへの自動fallbackはありません。
GitHubの[管理権限の仕様](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#administrative-privileges)と
[setprivの仕様](https://man7.org/linux/man-pages/man1/setpriv.1.html)を確認しています。

実モデルは既定で `NOT_RUN` です。利用可能なローカルembedding/chat endpointと資源を確認した
別の実行で、絶対pathの明示profileと実行flagを与えます。

```sh
bash tools/evaluate-semantic.sh local-model \
  --profile /absolute/path/semantic-profile.json --execute-local-model
```

profileは `schema_version: 1`、`profile_id`、
[LocalEmbeddingProfile](adr/0011-local-memory-embedding.md)相当の `embedding`、
answer用の `chat` を含みます。両profileは `enabled: true` を明示し、
固定したloopback `api_base`、model alias、model digest、15秒以内のtimeoutを指定します。
embedding次元はPoC上限2000以下です。chatは `max_tokens` を指定できます。
model digestは運用者の申告であり、サーバー内部のモデル真正性を暗号学的に証明しません。
profileやCLIから有料API、認証情報、任意の外部endpointへ切り替える経路は用意しません。
実行flagは新規モデルDL、GPU資源の占有、稼働サービス変更の権限を付与しません。

promptfoo 0.117.2のPython providerは呼出しごとに別Pythonプロセスを起動します。
現行Web文書のpersistent worker設定をこのpinへ適用しません。
JSON reportはこの版の `results.results` とversion 3を検査します。
raw reportには合成回答・変数・promptが含まれ得るため、
runnerが表示する `/tmp/core-semantic-eval.*` の私有directory内へ置きます。
公開証跡には必要なcase ID・出典metadata・集計・実行条件だけを転記し、
profileや将来の実データを混ぜません。失敗時もraw reportを公開せず、原因を識別した証跡を残します。

## 参照元と採用理由

参照元は公開 `FYuki/digital-souls` のcommit
`fce7382884d981c42be7fbd3ddaffe7469e27588` です。
取得時の公開mainとは異なるため、以下はすべて固定commitを指します。
合成評価ファイルだけを参照し、私的ログ・未追跡ファイル・資格情報を転記していません。

| 固定出典 | 採用・変更した点 |
| --- | --- |
| [package.json L5](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/package.json#L5) | promptfoo 0.117.2を合わせ、Core専用lockfileを用意 |
| [RAG manifest L17–48](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/evals/rag_retrieval/manifest.json#L17) | 出来事・嗜好をqueryから探す分類を参考に、同義語・言い換え・日本語/英語の独自合成ケースを作成 |
| [RAG manifest L52–74](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/evals/rag_retrieval/manifest.json#L52) | 関連度と順位を別に見る構造を採用。旧mention順、L2閾値、1次元vector、ゼロqueryは移植せずCoreの正cosineに合わせる |
| [RAG manifest L77–110](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/evals/rag_retrieval/manifest.json#L77) | 別character・削除・privacy除外を参考に、Binding全軸、明示source変更、複数source、dispatch前後の撤回へ拡張 |
| [semantic README L3–14](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/evals/semantic_memory/README.md#L3) | 合成goldの事前固定と結果に合わせて緩めない原則を採用。抽出・admissionの10分類や各90%閾値は今回の検索suiteへ移植しない |
| [semantic runner L73–80](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/scripts/eval_semantic_memory.py#L73) | promptへ渡す入力と期待値の分離を参考に、Coreでは別ファイルとcase_id限定のproviderへ強化 |
| [episodic README L24–31](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/backend/evals/episodic_quality/README.md#L24) | 欠落・重複・エラーを成功にしない集計と、gold非送信・LLM judge非使用を参考にする |

参照元のRAG manifestも合成vectorの回帰fixtureであり、実embedding品質の証跡ではありません。
privacy classifier、抽出器、記憶admission、旧Chroma/SQLite連携は今回追加評価しません。
既存の [記憶契約](memory.md) と [ADR 0013](adr/0013-pgvector-memory-poc.md) の
同意・由来・失効・検索上限を変更しません。
