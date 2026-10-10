# 本番経路による意味検索・回答評価

[ADR 0023](adr/0023-semantic-evaluation-contract.md) の固定した合成62ケースで、
検索はPython、回答はpromptfoo 0.117.2を使って測定します。
入力・gold・分類・移行対応・語句判定の限界は [評価README](../evals/semantic/README.md)、
本番の検索・context契約は [記憶API](memory.md) と [ADR 0022](adr/0022-memory-retrieval-from-records.md) が正本です。
[実モデル証跡](evidence/2026-10-09-semantic-real-model-evaluation-top5.md) に今回の3回の結果を記録しています。
品質は未受入です。fixtureの成功をモデル品質の合格にせず、実モデルのFAILも記録します。

## 評価経路と固定データ

[cases.json](../evals/semantic/cases.json) は入力schema 1、
[expectations.json](../evals/semantic/expectations.json) はgold schema 2です。
goldの分類・正解ID・禁止ID・期待順序・回答事実をモデルの入力へ含めません。
モデル依存の synonym / paraphrase / cross_language / unrelated は各10件、全26分類62件です。
評価結果を見る前に固定したケース・期待値・カード・プロンプトを使い、結果に合わせて変更しません。

各ケースはnetworkなし・公開portなし・digest固定の使い捨てPostgreSQL内で隔離します。
合成履歴を公開HistoryStore操作でappendし、Episode・Fact・EpisodeFactLink・Semanticを
`MemoryRecordStore.register` へ直接登録します。private化・出典削除・Fact更新等も公開操作を使います。
本番 `MemoryRetrieval` / `MemoryContext` を通し、回答は `Inference.prepare` / `Inference.check` とProvider portを使います。
逐語データや正本IDをモデル向けcontextへ注入する別経路は追加しません。

本番設定は候補20、最大5、relevance閾値0.52、同等帯0.002です。
採用モデルは [ADR 0024](adr/0024-multilingual-memory-embedding.md) の bge-m3 Q8_0（alias `bge-m3`、CLS、1024次元、接頭辞なし）です。
従来の nomic のFAILは上記証跡に保持し、この設定での実モデル再評価は #132 で行います。
unit vectorの二乗L2距離から `1/(1+sqrt(distance))` を求めます。
同等帯は `last_user_mentioned_at DESC NULLS LAST → created_at DESC → id ASC` で並べます。
Factは独立候補ではなく、有効なFactをEpisodeへ添付します。
検索ハーネスはembedding入出力からrelevanceを独立検算し、順位付け自体は製品へ任せます。

privacyは本番scanner・LocalClassifier・PrivacyPolicyを通しますが、分類器のprovider応答だけは
合成NOT_SENSITIVEです。`classifier=synthetic` と記録し、分類器品質は評価対象外です。
合成正本の直接登録は、会話から形成・保存・検索・利用までの実環境IT2/ST受入を置き換えません。

## 準備とmode

固定toolchainはuv 0.8.22、Python 3.12.3、Node 24.19.0です。
[開発規約](../CONTRIBUTING.md) に従い、依存取得にはネットワークが必要です。
評価ツールはモデル・GPU・サーバー・資格情報を用意しません。

```sh
uv sync --locked
(cd evals/semantic && npm ci --no-audit --no-fund)
```

回答の依存はnpm lockでpromptfoo 0.117.2と内部DBのbetter-sqlite3 13.0.3を固定します。
`.npmrc` はinstall scriptを全て無効にし、同梱N-API bindingを使用します。
対応bindingがない環境はFAILであり、自動でbuild/download scriptを許可しません。

| mode | embedding / 回答 | 品質証拠 |
| --- | --- | --- |
| `fixture`（既定） | 固定偽vector / 独立した回答fixtureをProvider portで返すfake | `quality_evidence=false`。道具の検証だけ |
| `local_model` | 明示したLocalEmbedding / llama.cpp Chat profile | 実モデルの合成セット測定。品質合格やbackend真正性とは別 |

検索はprofile指定時だけlocal_model、回答はmode・実行flag・profileを全て明示したときだけlocal_modelです。
回答のflag/profile不足はNOT RUN（exit 3）。無効profile・通信・不正応答・実行errorはFAILです。
fixtureへfallbackしません。検索local_modelでもembedding実呼出しが0ならquality_evidence=falseです。

## cacheなし3回の実行

fixtureでのハーネス検証:

```sh
bash tools/evaluate-semantic-retrieval.sh --runs 3 --output /dev/shm/retrieval-fixture.json
bash tools/evaluate-semantic-answer.sh --runs 3 --output /dev/shm/answer-fixture.json
```

承認された既存ローカルモデルでの測定:

```sh
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --profile /absolute/private/embedding.json --output /absolute/private/retrieval.json
bash tools/evaluate-semantic-answer.sh --mode local_model --execute-local-model --runs 3 \
  --profile /absolute/private/answer.json --output /absolute/private/answer-report.json
```

検索はvector cacheなしで毎回呼び直します。回答はpromptfoo `--no-cache` とcache無効環境を使い、
結果側でもcached=falseを検証します。各runは再試行なしで別promptfooプロセスを直列実行します。
全体が品質FAILでも3回の結果を残します。実行error・不完全reportは品質不合格と区別してFAILです。

## 私有profileとサーバー

profileはgit管理外の絶対パス（0700の私有ディレクトリ、0600のファイル）へ置きます。
[embedding例](../examples/embedding.example.json) と
[回答例](../evals/semantic/answer-profile.example.json) は無効な例であり、実サービスの設定ではありません。

`LocalEmbeddingProfile` はprofile_id・alias・GGUF SHA-256のmodel_digest・実dimensions・
loopbackのapi_base・timeout（最大15秒）・enabled=trueを明示します。
`AnswerProfile` はトップレベルenabled=true、上記embedding、chatを持ちます。
chatは `transport=llamacpp_chat`、`model=openai/gemma4-12b`、loopback api_base、
external_send_allowed=true、timeoutを設定します。chatのProfileにmodel_digestフィールドはないため、
回答GGUFのSHA-256は証跡で別に記録します。資格情報を要する経路へfallbackしません。

起動前にGPUのVRAM・他の推論処理を確認し、余裕がなければ起動しません。
既存コンテナの起動手順・主要設定は [llama.cpp運用](llamacpp-operations.md) を参照します。
health・`/v1/models` alias・GGUF digest・image digest・build・portを確認します。
bge-m3 のpoolingは `cls`、ctx/batch/ubatchは2048、parallelは1です。ubatchは最長入力のtoken数以上とし、
long_textの失敗があれば設定値と失敗を記録します。運用設定を変えた場合は理由を記録し3回をやり直します。
モデルの追加DL、他サービスの停止・変更、Ollamaの起動はこの評価手順に含めません。
評価後は失敗時も起動した評価コンテナを停止し、inspectのexitedを記録します。

## 採点と合否

| 対象 | 分類別の品質条件（各回90%以上） | 必須ゲート（各ケース全件合格） |
| --- | --- | --- |
| 検索 | relevant IDの全包含、該当なしの空結果、relevant Episodeへの必須Fact添付 | forbidden IDs/Fact不在、閾値未満混入0、正本検証、上位5件へのtop-1包含（fixtureは全順序一致も必須）、dispatch guard、context一致、no_match時の閾値以上適格候補0 |
| 回答 | grounded回答の全必須事実グループを満たす | 禁止事実不在、dispatch有効性一致と送信上位5件へのtop-1包含（無効時はID空）、送信/公開拒否と破棄、no_memoryの空context |

top-1はgoldの `expected_order` があればその先頭、なければ `relevant_ids` の先頭、空なら該当なしです。
期待値は変更しません。検索の `top_one` は両modeで必須、`expected_order` はfixtureだけに残し、
実モデルの品質ゲートには含めません。fixtureの62×3ではequivalent-band-orderの全順序を検証します。
回答は両modeで順序・余分な非禁止IDを問わず包含で判定し、top-1なしならID照合を省きます。
禁止ID・事実、valid=falseのID空、no_memoryの空context、lifecycleは維持します。

品質率は `quality_passed` の割合です。必須ゲートと分けて集計するため、分類品質100%でも
必須ゲート違反があればFAILです。全体件数の割合や3回平均で、90%未達の回・分類を相殺しません。
各1件の分類では1/1を要求します。該当なしの正常0件と、実行結果0件を区別します。

回答はNFKC→casefoldの部分文字列一致で、requiredは全グループAND・グループ内OR、
forbiddenはいずれかの候補の出現を違反とします。LLM judge・単語境界・文意解析は使いません。
複合語の誤一致や否定・時間関係を完全には判定できません。出典表記・回答言語は採点対象外です。
本番contextの検索後mutationをdispatch直前で再検証し、回答後mutationでは公開前に回答を破棄します。

欠落・重複・unknown ID・0件・実行error・非有限score・skip・cache利用・欠落assertion・
改変集計を拒否します。回答はraw exportをPythonで再採点し、metadataと照合します。
promptfooの平均scoreや終了コードだけでは合格にしません。
正常な完走のCLI終了値は全体PASS=0、品質または必須ゲートFAIL=1です。

## reportと公開証跡

| 項目 | 内容 |
| --- | --- |
| 共通manifest | commit.sha / dirty、mode、quality_evidence、classifier、embedding space、本番retrieval設定、case_version（schema・入力/gold SHA-256）、runs、passed |
| 各run | cases（ID・分類・quality_passed・gates・passed）、categories（total・passed・rate）、gates_passed・passed |
| 検索固有 | backend_identity_verified=false、embedding_call_count、取得ID・添付Fact ID・score・検証済みID・閾値以上適格候補数・dispatch/contextの観測 |
| 回答固有 | answer_model（profile_id・model・transport）、入力/カード/character/fixture SHA-256、promptfoo_version、toolchain（Node・内部DB依存版）、executions（attempts・exit_code・signal・raw_present・固定log分類）、送信ID・送信/破棄/空contextの観測 |
| 異常終了 | 回答は部分runsとfailure.stage / reasonを残す。検索の実行errorはreportを生成できない場合があり、終了値とNOT RUNの残る回を証跡へ記録する |

reportのmodel/revisionはprofileの宣言です。GGUFファイルを照合しても、接続先backendがそのモデルを
使用した真正性の独立検証にはなりません。quality_evidence=trueは品質合格を意味しません。

回答のraw export・生stdout/stderr・内部DBは専用0700一時領域へ保存し通常は終了時に削除します。
runnerは資格情報・proxy・dotenv・libpq・caller Node設定を子へ継承せず、Node通信も拒否します。
`--keep-private-artifacts` は明示診断用で、調査後にraw・生ログ・DBを削除します。
公開するのは本文・query・vector・回答全文を含まないreportだけです。公開前に構造と文字列値を確認します。

日付付き証跡には、cleanな実行commit・日時・コマンド・モデルalias/GGUF SHA-256・image digest/build・
server主要設定・起動前と評価中のGPU資源・ケース版・各回全体/分類/ゲート・失敗ケースID・終了値・
コンテナ停止確認・未検証範囲を記録し、安全なreportへリンクします。
分類器品質、形成〜利用の実接続、実運用DB適用、実環境IT2/ST、私的corpusの検索精度、
prompt injection耐性、速度・資源上限を、この合成セットの結果だけで合格としません。
