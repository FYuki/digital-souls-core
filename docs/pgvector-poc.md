# pgvectorによる派生記憶indexのPoC

この実験は合成source・memoryと合成vectorを使い、永続vectorの失効と検索を検証します。
本番の履歴・記憶schema、MemoryService、起動設定は変更しません。
設計判断は[ADR 0013](adr/0013-pgvector-memory-poc.md)を参照してください。

## 既存上限との関係

[記憶API](memory.md)の1000件は、1 Bindingのactive memoryを全件取得する検索経路の上限です。
保存件数を1000件に抑えるquotaではありません。`PostgresMemory._memories()` とSQLite版は
1001行目があれば413で拒否します。現在の意味検索はさらに全候補本文256 KiBを上限にします。
これは全候補の再認可と一時embeddingを有限にする制約で、性能測定から導いた閾値ではありません。

本PoCで10000件を扱っても、既存MemoryServiceの上限を解除したことにはなりません。
PoCの永続vector検索と、検索のたびに全本文を再認可・embeddingする既存経路は処理内容が異なります。
vector検索時間だけの比較から本番の応答速度を予測しません。

## 実験の境界

`experiments/pgvector_memory/` の明示的な実験APIを使い、`pgvector_poc_*` の独立schemaへ
合成sourceとmemoryのprojectionを投入します。本番DBからの自動importはありません。
元のCore PostgreSQL schemaへcolumn、trigger、functionを追加しません。
private/excluded/deletedは合成source snapshotの適格性fieldです。実threadのprivate変更や
発話除外から全sourceへ状態を同期する処理は未実装で、その伝播をこの試験で証明しません。

| 段階 | 確認するもの | 確認しないもの |
| --- | --- | --- |
| source・memory更新 | 同transactionでの派生vector消去と世代失効 | 本番history adapterへの透過接続 |
| vector採用 | WorkItemのversion/source/spaceを使ったCAS | 実embeddingモデルの真正性・品質 |
| SQL exact検索 | Binding、適格性、space、正cosine、順位 | HNSWの性能・recall |
| 検索後token検証 | 返却後の更新・撤回・space変更の検出 | 実MemoryContextから最終推論までの結線 |
| 合成benchmark | 部分処理の時間と容量 | 本番の全体遅延や実会話での検索品質 |

sourceはsource IDに加えて明示的なconversation/turn/message/epoch、memoryはBindingとIDに加えてprojection revision・
本文hash・index generationを持ちます。derived embeddingはそれらの状態へ従属します。
本文hashやvector自体を「秘密情報ではない」と扱って外部出力しません。

## 生成・変更・検索の契約

`put_source()` の変更は関連memoryの旧本文とvectorを同じtransactionで消し、
旧完了結果が採用されないようrevision/generationを進めます。
private解除やsourceの再有効化だけでは旧vectorは戻りません。
`put_memory()` は明示的な追加・更新・再構成をpendingにします。
ready/pendingなら同IDで本文更新できますが、invalid/deletedの旧IDは再利用せず、再構成には新しいIDを使います。
`prepare()` と `complete()` の間に行った変更は、完了側のCASが検出します。

memory削除では本文とvectorを同transactionで消します。scope移動では旧Binding側を失効させ、
新Bindingのsourceを確認してから新たなpending対象を作ります。移動先にあるtombstone IDも再利用しません。
複数sourceの一部が失効したときは旧memoryを即時に利用停止し、残る適格sourceだけの明示再構成を要求します。
`set_space()` でmodel/revision/dimensions/configurationを変更した場合も、古いvectorとtokenを失効させます。

検索は全Binding軸、現在のsource、memory状態、spaceをSQLで絞ってexact cosineを計算します。
合成query vectorを入力し、正cosineだけを返します。同点は作成順の新しいものを先にし、
同IDの本文更新では作成順を変えません。結果limitはPoC専用の1〜1000です。
返却した `SearchHit.token` は `valid(token)` による再検証に使います。
これは将来のdispatch guardへ渡すための接続点です。現在のPoCには本文の分類・認可、
MemoryServiceへの注入、モデルへのdispatchはありません。

## 検証対象

受入試験には次を含めます。個々の実施結果は日付付き証跡で確認し、この一覧をPASSの記録として扱いません。

- Binding全4軸の分離、private、指定source除外、削除、部分source失効、scope移動。
- memory本文更新とembedding space変更、private on/off、space A/B/A後の旧vector非復活。
- 生成開始後の変更、完了の重複、順序逆転、削除後の遅延完了、transaction rollback。
- 検索後の撤回でtoken無効、元memory IDと非ゼロmessage index・複数turnを含むsource保持、全候補失効時の空結果。
- float32へそろえたPython exactとSQLの一致、正cosine、同点、次元/非有限/ゼロvectorの拒否。
- 既存schemaと起動設定の非変更、実履歴・実モデル・GPUを使わないこと。

専用runnerは開発用の使い捨てPostgreSQL 18.6 + pgvector 0.8.7を用意します。
imageは `pgvector/pgvector:0.8.7-pg18-bookworm@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11` です。
ネットワークなし・公開ポートなし、1 CPU・1 GiB・pids上限128・tmpfsの専用コンテナへ、
明示したUnix socketで接続します。dogfoodや既存PostgreSQL serviceを検証先にしません。

```sh
bash tools/test-pgvector-poc.sh
```

runnerは `uv run --no-sync pytest -m pgvector -q` を実行します。
接続設定は専用の `DSC_PGVECTOR_POC_SOCKET`、`DSC_PGVECTOR_POC_PORT`、
`DSC_PGVECTOR_POC_DATABASE`、`DSC_PGVECTOR_POC_USER` の4変数です。
本番のPG環境変数や認証情報を取り込まず、必須設定の欠落をskipで成功扱いにしません。
実施件数・結果・制約はrunnerと日付付き証跡に対応づけます。

## 合成benchmarkの読み方

比較用データは固定seedで生成した100/1000/10000件、128次元を基本とします。
同じfloat32 vectorをSQLとPythonへ渡し、positive cosineと返却ID・順序を検証します。
要素が有限でもfloat32のnorm計算がoverflow・zero underflowする値はPoCの入力範囲外として拒否します。
本文・vectorそのものをレポートに出さず、件数・時間・容量・検証結果を出します。

使い捨てfixture内でbenchmarkを実行する例です。既存サービスのsocketへ値を置き換えません。

```sh
bash tools/test-pgvector-poc.sh -- bash -c '
  uv run --no-sync python -m experiments.pgvector_memory.benchmark \
    --socket "$DSC_PGVECTOR_POC_SOCKET" \
    --port "$DSC_PGVECTOR_POC_PORT" \
    --database "$DSC_PGVECTOR_POC_DATABASE" \
    --user "$DSC_PGVECTOR_POC_USER"
'
```

既定はseed 20261005、8 query、warmup 2回、測定5回、limit 8です。
`--sizes`、`--dimensions`、`--seed`、`--queries`、`--warmup`、`--repeats`、
`--limit` で条件を明示できます。dimensionsは128または384、件数は10000以下です。
変更した条件は出力と一緒に保存し、異なる条件の値を同じ測定として混ぜません。

生成時間、DB投入時間、更新費用、relation容量、SQL検索と転送を含む時間、
serverのEXPLAIN時間、候補取得時間、Pythonの順位付け時間を分けて記録します。
繰返し測定はp50/p95と条件を添えます。query数や繰返し回数が小さい場合のp95を、
運用時のtail latency保証として扱いません。

実embedding生成時間はNOT RUN、モデル品質のevidenceはfalseです。
HNSWの評価は既定でNOT RUNとし、実施した場合もexactの結果と別の項目で比較します。
source適格性確認の費用、SQL計画、転送量、単一schema lockによる直列化を含めて読み、
「vector演算だけが速い」ことを本番採用の十分条件にしません。

## 後続に必要な判断

本番へ接続するには、履歴変更と派生index消去の同一transaction化、既存schemaのmigration契約、
現在のpolicyでの本文認可、検索設定stampとtokenを含むdispatch guardの結線が必要です。
既存の抽出job provenanceと検索設定は分けたままにします。

本PoCはそのための削除・CAS・検索primitiveを評価するもので、本番採用、1000件上限撤廃、
実モデル精度、並行負荷、backupからの消去、常駐worker運用を承認・検証したものではありません。

関連Issue: [#48](https://github.com/FYuki/digital-souls-core/issues/48)。

## 実施結果

2026-10-05の[境界試験・規模別比較](evidence/2026-10-05-pgvector-poc.md)と
[生の測定JSON](evidence/2026-10-05-pgvector-benchmark-128.json)を参照してください。
