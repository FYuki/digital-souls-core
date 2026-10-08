# 意味検索・回答評価ケース固定の実施証跡

対象: [Issue #112](https://github.com/FYuki/digital-souls-core/issues/112)、[Epic #111](https://github.com/FYuki/digital-souls-core/issues/111)。

起点: `12ff21c5f55dbda32a301391bc0d0505ed5316a9`（`epic/semantic-evaluation-redo`）。
作業branch: `feature/112-evaluation-cases`。2026-10-09に実行。

## 変更と範囲

[ADR 0023](../adr/0023-semantic-evaluation-contract.md)でV1〜V7・旧評価の置換を記録しました。
[評価データREADME](../../evals/semantic/README.md)に62ケースの分類件数・旧19件の対応と公開操作への読み替えを示しました。
[検証モジュール](../../src/digital_souls_core/semantic_evaluation_cases.py)はstrict/extra forbidの入力とgoldを別型で読み、参照・citation・vector・初期登録構造を純粋に検証・変換します。

先にUTを書き、モジュール未作成の `ModuleNotFoundError`（collection error）でREDを確認しました。
追加UTのREDで、除外Episodeを根拠にするSemanticが登録batchに残る検証漏れを確認し、修正しました。
最終UTは49件追加で、うち43件は不正データ拒否のparametrizeです。
残る6件はデータ変換・件数/旧対応・gold分離・本文非開示・domain値保持・純粋な本番順位関数との整合です。

入力にgoldを混入せず、同一本文の偽vectorを統一しました。旧ミント本文は同義語ケースの非関連候補と日英ケースの関連候補でvectorが矛盾していたため、日英ケースのquery軸を合わせています。
これはCIの道具の検証用であり、モデル品質の証拠ではありません。

## 品質ゲート

共通環境:

```sh
T=/home/asa/dev/digital-souls-evidence/history-stage1-tools
export PATH=$T/bin:$T/node/bin:$PATH
export TMPDIR=/dev/shm
```

`uv --version`: **uv 0.8.22**、`node --version`: **v24.19.0**。

| コマンド | 最終結果 |
| --- | --- |
| `uv sync --locked` | PASS、80 packages resolved / 78 installed packages audited |
| `uv lock --check` | PASS、lock変更なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS、102 files |
| `uv run --no-sync mypy` | PASS、102 source files |
| `uv run --no-sync pytest -m ut -q` | PASS、522 passed / 977 deselected |
| `uv run --no-sync pytest -m it1 -q` | PASS、579 passed / 920 deselected |
| `uv build --no-build-isolation` | PASS、sdistとwheel生成 |
| `bash tools/test-postgres.sh` | PASS、398 passed / 1101 deselected、使い捨てDocker PostgreSQL |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/*.test.mjs` | PASS、27 registered required tests |
| `node tools/check-docs.mjs` | PASS、新規ファイルをstageした状態で確認 |
| `git diff --check` / `git diff --cached --check` | PASS |

実装途中のruff/mypy指摘は修正し、最終検査を再実行しました。途中のFAILをPASSとして扱いません。
pytestのdeselectedは別markerの試験で、SKIPではありません。skip/xfail/xpassはありません。
StarletteのBlockingPortal非推奨警告、PydanticのReadOnlyに関する既存警告は残っています。

| 試験 | 起点の件数 | 最終件数 | 増減理由 |
| --- | --- | --- | --- |
| UT | 473 | 522 | +49、検証/変換・固定データの試験追加 |
| IT1 | 579 | 579 | 変更なし |
| PostgreSQL | 398 | 398 | 変更なし、新データの実登録試験はIssue #113 |
| Node | 27 | 27 | 変更なし |

## 後続と未実施

- 新ケースのPostgreSQLへの実登録・本番MemoryRetrieval/contextを使うハーネス: **NOT RUN / 未実装**、Issue #113の範囲。
- promptfoo回答評価: **NOT RUN / 未実装**、Issue #114の範囲。
- 実モデル・cacheなし3回の品質評価、実環境IT2/ST: **NOT RUN**、この変更の合成PASSで代用しません。
- 旧fixture・旧ツール・memory_evaluation.pyの撤去と利用文書同期: 未実施、ADR記載の後続Issueへ引継ぎ。
- push・PR作成・merge: 未実施、監督の担当。

未解決の製品判断はありません。実装詳細として、会話の論理IDを後続ハーネスで生成IDへ一括写像する形式、Fact添付用goldを候補IDと分ける形式、dispatch直前と応答公開前の判定を区別する形式を採用しました。
