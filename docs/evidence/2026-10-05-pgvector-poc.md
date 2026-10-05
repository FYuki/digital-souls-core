# pgvector派生記憶PoCの境界検証と合成比較

2026-10-05 UTC。[Issue #48](https://github.com/FYuki/digital-souls-core/issues/48)、
[ADR 0013](../adr/0013-pgvector-memory-poc.md)（Proposed）の独立PoCです。
本番store/schema、PR #46、main、dogfoodの設定は変更していません。

## 結果と判断

固定した合成float32 vectorでは、PostgreSQL exactと既存Python `rank_memories` の順位が
100/1000/10000件の各56検索、合計168検索で一致しました。最大score誤差は約5.61e-8で、
許容値1e-5以内です。private/除外/削除・他Bindingの混入は0件でした。

pgvectorによる永続化とexact検索を、本番結線の次の候補として進める根拠が得られました。
100件ではDB往復がPython計算だけより高く、1000/10000件ではPG側の順位計算が低コストでした。
全候補vectorの転送も省けます。ただし、実embedding生成や認可・最終dispatchを含む
本番応答時間を測った結果ではありません。

HNSWはNOT RUNです。今回はexactの削除・競合・順位一致を先に確認しました。
ANNを追加するとrecallとfilterの実行計画も別に検証する必要があり、現行の全source照合や
単一schema lockをそのまま高速化できるとは限りません。Chroma比較は、この段階の
同一transactionでの撤回検証に追加基盤が不要なため行っていません。

## 計測値

128次元、k=8、seed=20261005、query 8件、warmup 2周、計測5周（各規模40 samples）。
単位はms、各欄はp50 / p95です。

| 記憶件数 | PG exact・往復込み | Python計算のみ・候補保持済み | 全vector転送・復号＋Python計算 |
| --- | --- | --- | --- |
| 100 | 5.33 / 5.82 | 2.54 / 2.69 | 10.56 / 11.75 |
| 1,000 | 12.71 / 13.44 | 25.64 / 26.36 | 72.19 / 79.50 |
| 10,000 | 93.10 / 98.13 | 270.90 / 287.99 | 737.69 / 756.68 |

PG欄はsource適格性照合、SQL順位付け、上位結果の由来取得、接続/往復を含みます。
Python欄は同じ保存済みfloat32を使った順位計算の比較であり、既存MemoryServiceの
「query＋全候補本文を毎回embeddingする」全経路の測定ではありません。
10000件は現行の1000件検索上限を越えたprimitive試験です。既存上限は変更していません。

| 記憶件数 | 初期vector投入 秒 | ANALYZE ms | 1件更新 p50 / p95 ms | 更新前relation総量 MiB |
| --- | --- | --- | --- | --- |
| 100 | 0.179 | 5.29 | 11.71 / 12.10 | 0.60 |
| 1,000 | 1.870 | 12.43 | 11.31 / 11.50 | 2.61 |
| 10,000 | 21.948 | 65.76 | 12.82 / 13.68 | 22.76 |

投入は本文・由来・vectorを含むPoCの検証付き処理です。更新は `put_memory+prepare+complete`
の3transactionで、合成vectorを渡す費用を含み、モデル生成時間を含みません。
schemaと通常B-tree索引の初期作成は約8ms、source登録100件は約0.30秒でした。
relation総量は本文・由来・metadata・通常索引を含みます。ANN索引の構築費用ではありません。
永続vectorの作成・更新費用を検索時間から分離しています。

実embedding生成時間・検索品質は **NOT RUN**、`model_quality_evidence=false` です。
合成vector生成時間はJSONの `synthetic_generation_ms` に別記しました。

## 環境と再現

- Ubuntu 24.04 / WSL2 x86_64、Python 3.12.3、uv 0.8.22、psycopg 3.3.6、Node 24.19.0。
- PostgreSQL 18.6 / pgvector 0.8.7。公式image
  `pgvector/pgvector:0.8.7-pg18-bookworm@sha256:2358fcba361ed2233a5ed81b5fe4ca779ccb304120ce531a3bf51c0ed7e2bc11`。
- 専用container、network none、公開portなし、0700 Unix socket、tmpfs、DB 1 CPU / 1 GiB。
  client affinityはCPU 0/1、address space上限1 GiB、peak RSS約262 MiB。
- shared_buffers 64 MiB、work_mem 4 MiB、JITはonだが測定planでJIT実行なし。
  10000件ではtemp書込842 blocksがあり、materialized候補の一時領域使用を含みます。
- 合成投入後にPoC内の5tableだけANALYZE。cold cache・未ANALYZEの初期統計状態・運用autoanalyzeはNOT RUN。
  PostgreSQL/Pythonの計測順はqueryと反復ごとに交互にしています。
- 計測期間 `2026-10-05T05:19:34.438123+00:00` ～ `2026-10-05T05:21:07.757442+00:00`。
  DB開始時刻と対象source hashが途中で変わっていないことを検証しました。

実測は保持した専用fixtureに対して次を実行しました。

```sh
LITELLM_LOCAL_MODEL_COST_MAP=True .venv/bin/python -m experiments.pgvector_memory.benchmark \
  --socket /tmp/core-pgvector-poc-607g0j25/socket \
  --sizes 100 1000 10000 --dimensions 128 --seed 20261005 \
  --queries 8 --warmup 2 --repeats 5 --limit 8 \
  --output docs/evidence/2026-10-05-pgvector-benchmark-128.json
```

再現時は [専用runner](../../tools/test-pgvector-poc.sh) で新しいfixtureを作り、
その `DSC_PGVECTOR_POC_SOCKET` を使います。既存DBのsocketへ付け替えません。
詳細は [PoC手順](../pgvector-poc.md) を参照してください。

実測時はコミット前で、base HEADは `2f4faaf749d022c688d13afd54a3296bba8dc74f`、dirty=trueでした。
[生のJSON](2026-10-05-pgvector-benchmark-128.json) の `source.files_sha256` にstore/schema/
benchmark/synthetic/既存ranker/lockの実行時hashを保持しています。本証跡作成時も一致を確認しました。
このbase SHAだけをPoC実装のcommitと扱わないでください。

## 必須検証

| 検証 | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS、製品依存の追加・変更なし |
| Ruff lint / format | PASS |
| mypy strict | PASS、76 source files |
| UT `pytest -m ut -q` | PASS、274件 |
| IT1 `pytest -m it1 -q` | PASS、746件 |
| 既存 `bash tools/test-postgres.sh` | PASS、83件 |
| 新規 `bash tools/test-pgvector-poc.sh` | PASS、52件、独立fixtureの作成・cleanup込み |
| Node文書検証・必須test reporter | PASS、23件、skip/TODO/cancelなし |
| wheel build / hash固定offline install / isolated import | PASS、wheel runtimeにexperimentsなし |
| 合成exact比較 | PASS、168検索・score誤差内・filter混入0 |
| 実モデル品質・本番IT2/ST・HNSW | NOT RUN |

PoCの52件は全Binding軸（未対応audienceは拒否）、正cosine/同点/数値異常、
複数sourceの部分撤回、source位置・revision・epoch、本文更新、削除、scope移動、
source/spaceのA→B→A、旧ID再利用拒否、生成完了CAS、検索後token失効、rollbackを検証します。
独立reviewで見つかった旧本文残存、libpq暗黙routing、由来省略、teardown接続のguard不足は
修正し、対応する回帰試験を追加しました。最終reviewに未解決の重大指摘はありません。

途中のFAILも区別します。初回は新testの誤ったimportでcollection/type検査が失敗し、修正後に
上表の全体試験が成功しました。編集途中のbenchmark書式違反も最終format後に解消しています。
wheel確認をcheckoutのcwdから行うと依存importがcwdを探索しPoCを見つけたため、空のcwdに
分離してinstalled packageだけを確認しました。wheelへのPoC混入ではありません。
最初の保持fixtureはWSL呼出し間で消失したため採用せず、CLIセッションを保持して新規fixtureを
作り直しました。採用した測定ではDB再起動なしです。

## 本番結線と必要権限

これは合成authoritative projectionであり、Coreの本番履歴・認可・dispatchへは未結線です。
実配備を進める前に次を別途具体化します。

1. 管理者による公式pgvector extensionの導入とDB内の拡張有効化。runtime roleに拡張作成権限を渡さない。
2. 既存の厳格なschema検証と整合するversion/migration契約、派生tableの管理者所有・最小runtime権限。
3. private/指定発話除外/削除/訂正/公開範囲の変更と、本文・vector無効化を本番adapterの同じtransactionへ結線。
4. 明示的なembedding worker、モデル/次元/設定変更、失敗・再試行・再構築の管理。
   正本会話を勝手に取り込まず、既存の採用済み記憶だけを対象にする。
5. query/結果の本文認可、各await後とdispatch直前の既存guardにsource/index tokenを加える。
   PoC `valid()` は認可を与えるAPIではない。
6. 実モデル・実次元での品質/時間、単一schema lockの分割、並行負荷、対象環境でのSQL計画・容量を再評価。

現在のruntime上限1〜4096次元に対しPoCは1〜2000次元です。自動で本番契約を狭めません。
削除検証は可視SQL状態と検索結果が対象であり、WAL/backupを含む物理消去の証明ではありません。
main取り込み・Core切替・dogfoodへの拡張導入は行っていません。
