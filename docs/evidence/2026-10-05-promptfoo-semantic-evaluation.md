# 2026-10-05 promptfoo意味検索評価の証跡

## 対象とrevision

- Issue: [#50](https://github.com/FYuki/digital-souls-core/issues/50)
- main起点: `c10bd09052dea26af81a7110e2ad1a9808c80236`
- 固定依存: [Draft PR #49](https://github.com/FYuki/digital-souls-core/pull/49)
  の `b5facfd6b98faec289a6ef3bd8e52697ff9db833`
- branch: `feature/promptfoo-semantic-evaluation` → `epic/semantic-model-evaluation`
- 参照元: 公開[digital-souls commit](https://github.com/FYuki/digital-souls/commit/fce7382884d981c42be7fbd3ddaffe7469e27588)
  `fce7382884d981c42be7fbd3ddaffe7469e27588`。公開main `7a11b2d`とは別のcommitであり、
  GitHub APIで到達可能性を確認した。追跡済み評価資産のみ読み、未追跡ファイルは使用していない。
- 採用・変更理由と固定版の制約: [評価手順](../promptfoo-semantic-evaluation.md)、
  [ADR 0014](../adr/0014-promptfoo-semantic-evaluation.md)

独立worktree内の評価用変更であり、製品の履歴・記憶経路、既存PR #46/#49、
稼働中のCoreを変更しない。元の128次元合成性能比較はこの評価に混ぜない。

## 実モデルの可用性確認

2026-10-05 05:52 UTCに、サービス状態、モデルメタデータ、GPU使用量を読み取り確認した。
推論リクエスト、embeddingリクエスト、新規モデルのダウンロード、サービス操作は行っていない。

| 確認項目 | 結果 |
| --- | --- |
| Core | PID 1912、`127.0.0.1:18080`、`c10bd09`、stateless、drop-inなし |
| chat registry | `openai/gemma4-12b` → `http://127.0.0.1:18081/v1` |
| 読み取りAPI | `/v1/models`、`/health`、`/props`が応答。モデル`gemma4-12b`、llama.cpp `b11347-5fc4f3c8c` |
| chat起動設定 | context 4096、parallel 1、GPU layers 99。embedding/poolingフラグなし |
| embedding | 専用サービスは確認できず。chatモデルから適性やAPI対応を推定していない |
| GPU | RTX 4070 Ti SUPER、16,376 MiB中12,269〜12,283 MiB使用、36〜37%稼働 |

GPU利用タスクは権限制約により特定できなかった。実embedding品質・実生成回答品質はともに
**NOT_RUN**。利用するembeddingモデル・endpointの確定とGPU利用枠の調整が必要である。
新規モデルのダウンロードやサービス追加を選ぶ場合は、対象と構成を示して利用者の許可を得る。
既存chatの可用性確認はembeddingの互換性検証ではない。

## 合成データによる検証

最終の[機械可読集計](2026-10-05-promptfoo-fixture.json)へ、入力・正解・provider・
採点器・runner・lockfile・CIを含む29ファイルのSHA-256と結果を保存した。
実行前後のhashはすべて一致し、並行編集中のsmokeとは区別している。

| 検証 | 結果 |
| --- | --- |
| promptfoo retrieval | 20 / 20 PASS、全必須ゲートをraw outputから再検査 |
| promptfoo answer | 20 / 20 PASS、失効後の回答破棄・引用を検査 |
| fixture recall | 関連IDがあるケースの平均1.0。空正解ケースは分母へ含めずnull |
| 境界・検索品質・回答品質の失敗 | 両suiteとも0 |
| embedding / chat呼出し | 両suiteとも0 |
| Node必須テスト | 92 PASS（gate 60、runner 9、既存文書23） |
| Python UT | 335 PASS、skipなし |
| Python IT1 | 746 PASS、skipなし |
| ruff / format / mypy | PASS、86 source files |
| build / locked install / import | PASS、空cwdからevals・experiments非混入を確認 |
| 文書リンク / git diff --check / shell構文 | PASS |
| 実モデル品質 | NOT_RUN、`quality_evidence: false` |

Node 24.19.0、uv 0.8.22、Python 3.12.3、promptfoo 0.117.2、PostgreSQL 18.6、
pgvector 0.8.7を使用した。promptfooのbetter-sqlite3 11.10.0は、同梱sourceと
固定Node headersを使い、通信不能のnamespace内で限定ビルドした。

```sh
uv sync --frozen
npm ci --prefix evals/semantic --ignore-scripts --no-audit --no-fund
bash tools/build-semantic-sqlite.sh
uv run --no-sync ruff check src tests experiments evals tools/evaluate-memory-search.py
uv run --no-sync ruff format --check src tests experiments evals tools/evaluate-memory-search.py
uv run --no-sync mypy
uv run --no-sync pytest -m ut -q
uv run --no-sync pytest -m it1 -q
node --test --test-reporter=./tools/required-tests-reporter.mjs evals/semantic/*.test.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
bash tools/evaluate-semantic.sh fixture
node tools/check-docs.mjs
uv build --no-build-isolation
git diff --check
```

locked wheel installと空cwdからのimport確認は[API CI](../../.github/workflows/api.yml)と
同じ手順で実行した。新しい[評価CI](../../.github/workflows/promptfoo.yml)はすべてのPRと
main/epicへのpushで動き、秘密情報や実モデルを必要としない。
GitHub上の最終headと実行結果はDraft PRのチェックから参照する。

最初のCLI統合試験はFAILだった。固定版の`--no-write`で公式JSON exportの詳細行が空になり、
report gateが欠落を拒否した。gateを緩和せず、専用の私有一時state内へ合成評価を保存し、
公式exportを使う方式に変更した。独自hookによる結果補完はしていない。
raw report・SQLite状態・ログは私有一時directoryに留め、公開集計には本文・profileを含めない。

独立レビューでは、モデル設定の固定、cacheの結果再利用の拒否、通信遮断、出典と失効、
検索missと境界違反の分離を確認し、追加のblocking指摘はなかった。
CodeRabbitの実レビューは依頼していない。epic→mainのレビュー条件を満たしたとは扱わない。

provider関連3ファイルの一括コピーは、既存変更を上書きする可能性を理由に自動承認レビューが
拒否し、未実行となった。元ファイルを読み、AST・SHA-256で所有範囲を確認して保全したうえで、
hash前提の限定patchが承認され実行された。拒否されたコピーの再試行はしていない。

`src`、既存PoC、`uv.lock`は固定依存から無変更。使い捨てpgvector containerはrunner終了時に
削除された。本番履歴の取込、GPU推論、新規モデルDL、稼働系設定変更、mainマージは行っていない。


## GitHub runner固有の隔離起動

初回head `539012ad072cd214bf467a87743047784647d37e` の
[新評価CI](https://github.com/FYuki/digital-souls-core/actions/runs/37272750330)は、
依存606 packageの取得後、`unshare` の `/proc/self/uid_map` 書込み拒否でFAILとなった。
これはGitHub runnerのOS制約であり、自動承認レビューの拒否とは別である。
同headのAPI・PostgreSQL・pgvector・文書CIはPASSだった。

ホストの保護設定を緩めず、CIだけで固定system commandを使ってnetwork namespaceを作り、
元の非root UID/GID・補助groupなし・capabilityなし・no-new-privilegesの状態へ戻してから
build/評価を起動する方式を追加した。ローカルsudoは実行していない。
通常のローカル実行は一般ユーザーのnamespaceを使い、失敗時の通信可能なfallbackはない。
最終のGitHub CI結果はPRの最新headに紐づくcheckを確認する。

CI専用helperのmock UTは23件PASS。修正後のローカルnative buildと40評価も、
一般ユーザーのnetwork namespaceだけで再実行しPASSだった。実行前後のsource hashは一致した。
