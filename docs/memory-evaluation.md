# 合成データによる意味検索評価

[記憶検索](memory.md)の順位付けを、明示的な正解IDを持つ合成corpusで測定します。
既定は偽embeddingを使うoffline実行です。実モデルの評価には、運用者が明示したローカルprofileを使います。
どちらも合成セット内の結果を報告するだけで、モデルの採用や「品質が良好」という判定は行いません。
実モデル・GPU・dogfoodへの接続と実測は、このsliceではNOT RUNです。

## 通信なしの再現手順

リポジトリの固定toolchainを用意し、通常のlocked installが完了した環境で実行します。
ハーネス自体がモデル・依存・認証情報を取得することはありません。

```sh
uv run --no-sync python tools/evaluate-memory-search.py
```

既定では[配布fixture](../tests/fixtures/memory-retrieval-evaluation.json)を使い、`k=2`のJSON reportを
標準出力へ返します。`mode`は`fixture`、`quality_evidence`はfalseです。
fixtureに書かれたvectorで順位付けと指標の実装を確認するため、良い数値でもモデル品質の証拠になりません。

fixtureとkを明示する場合は次の形式です。

```sh
uv run --no-sync python tools/evaluate-memory-search.py \
  --fixture tests/fixtures/memory-retrieval-evaluation.json --k 2
```

## 明示profileによるローカル実測

[profile例](../examples/embedding.example.json)は`enabled=false`の合成値です。
実測には、承認されたローカルembeddingモデルのalias・digest・実次元・endpointを確認した別profileを
用意し、`enabled=true`を明示します。例ファイルの値が稼働中サービスに対応するとは扱いません。

```sh
uv run --no-sync python tools/evaluate-memory-search.py \
  --profile /absolute/path/to/approved-embedding-profile.json --k 2
```

`--profile`を渡した場合だけ`LocalEmbedding`を読み込み、queryと候補の合成本文をそのloopback endpointへ
送ります。通信先、timeout、SDK、エラーの契約は[ADR 0011](adr/0011-local-memory-embedding.md)と同じです。
profileが無効・不正、接続不能、不正応答の場合は失敗し、偽embeddingへfallbackしません。

llama.cppの`/v1/embeddings`には`none`以外のpoolingが必要です。embedding用途に対応したモデルと
server設定を確認してください。既存chat用gemmaモデル・portとの互換性は未確認です。
[llama.cpp公式server仕様](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md#post-v1embeddings-openai-compatible-embeddings-api)を参照してください。

実測reportは`mode=local_model`になり、embeddingを1回以上呼び出した場合だけ`quality_evidence=true`に
なります。全queryの候補が0件なら呼出しはなく、この値はfalseです。`embedding_call_count`で呼出し件数を
確認できます。これは指定したbackendから得たvectorで合成セットを測定した、という区別です。backendの真正性は確認せず、
`backend_identity_verified=false`を併記します。model digestはprofileの宣言であり、接続先が実際にその
モデルを使った証明ではありません。実世界の検索精度・privacy分類精度や品質合格を意味しません。

## fixtureと検索範囲

fixtureはJSONで、`dataset_type`は`synthetic`、versionとdimensionsを持ちます。

| 要素 | フィールドと意味 |
| --- | --- |
| `documents` | `id`、合成`text`、source参照、偽`vector` |
| `source` | `conversation_id`、`turn_revision`、`message_index`、`epoch` |
| `queries` | `id`、合成`text`、`candidate_ids`、`relevant_ids`、`excluded_ids`、偽`vector` |
| `candidate_ids` | そのqueryで順位付けできる候補ID |
| `relevant_ids` | 正解ID。候補の部分集合で、除外IDと重ならないこと |
| `excluded_ids` | embeddingへ渡す前に候補から取り除くID |

不明・重複IDや正解集合の不整合は拒否します。候補が0件ならembeddingを呼びません。
同じquery内では製品と同じ`RetrievalPolicy`の順位付け（relevance 0.54以上、同等帯）を使い、返却件数だけkに合わせます。同等帯ではfixtureの候補順です。
local modeではfixtureの偽vectorを品質値として使わず、実adapterから得たvectorを評価します。

このハーネスは合成の候補・正解集合を直接扱います。`excluded_ids`の除去は評価入力の制御で、
実際のprivate thread、発話除外、削除transaction、Binding、privacy分類の結合試験を置き換えません。
これらはMemoryService/SQLiteのUT・IT1で別に検証します。正本の履歴DBを読み込む機能はありません。
`dataset_type=synthetic`というラベルだけで実データが安全になるわけではなく、私的実会話をfixtureへ転記しません。

## 指標の定義

正解が1件以上あるqueryを`answerable`、0件のqueryを`unanswerable`として区別します。
上位k件に入った正解数をh、正解総数をrとします。

| 指標 | 定義 |
| --- | --- |
| Recall@k | h / r。正解のうち取得できた割合 |
| Precision@k | h / k。返却がk件未満でも分母はk |
| Reciprocal rank | 最初の正解の順位の逆数。上位k件に正解がなければ0 |
| MRR@k | answerable queryのreciprocal rankの平均 |
| unanswerable empty rate | unanswerable queryのうち空結果を返した割合 |

Recall・precision・MRRの平均はanswerableだけを対象とします。answerableで空結果なら各値は0です。
unanswerableのquery別Recall・precision・reciprocal rankはnullとし、空結果の割合を別に集計します。
集計対象queryが0件の場合、その平均や割合もnullです。正解なしのqueryを成功値1として混ぜません。

## reportと証跡

reportは`fixture_version`、mode、quality_evidence、`synthetic_only=true`、backend識別の状態、
`space`、k、`embedding_call_count`、query件数、answerable/unanswerable件数、空結果件数、各平均指標を含みます。
query別にはID、retrieved/relevant/excluded IDs、候補数、answerable、空結果かどうか、各指標を返します。
本文・vector・由来本文をreportへ複製しません。`space`はmodel/revision/dimensions/configurationの宣言です。

実測時の証跡には、Coreの正確なrevision、fixture version、コマンド、日付、実行環境、モデルの確認方法、
server revisionとpooling、profileの機密情報を含まない識別、report、失敗・制約を記録します。
指標が低くても実行成功と品質合格を同一視せず、profile失敗や未実行をPASSとしません。
サーバー本文ログ、私的会話、資格情報を証跡へ含めません。

この評価だけではprivate化・削除の安全性、全話題の意味理解、prompt injection耐性、速度・資源上限を
証明しません。実運用の対象corpus・採用基準・追加評価は別途定めます。
