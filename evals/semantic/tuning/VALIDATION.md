# Issue #129 実装検証（2026-10-10）

起点: `86b7e243cc57845024f1420382274a6d6f0785f0`、branch `feature/129-tuning-cases`。
実装・ローカル検証だけを担当。push・PR作成・mergeは監督の担当で、実行していません。
実モデル・GPU・llama.cppコンテナは使っていません。
分類別件数・独立性・外部補助データの出典と版は [README](README.md) を参照してください。

## 環境と最終ゲート

全コマンドは指定された `129-tuning-cases` worktreeで実行しました。

```sh
T=/home/asa/dev/digital-souls-evidence/history-stage1-tools
export PATH=$T/bin:$T/node/bin:$PATH TMPDIR=/dev/shm
```

uv 0.8.22 / Node 24.19.0。次のlint/format対象（`P`）には追加したPythonも含め、
CIのlint/formatとmypy設定へ追加しています。

```sh
P="src tests tools/evaluate-semantic-retrieval.py tools/prepare-semantic-tuning-supplements.py evals/semantic/provider.py"
```

| コマンド | 最終結果 |
| --- | --- |
| `uv sync --locked` | PASS、80 packages解決 |
| `uv lock --check` | PASS、lock変更なし |
| `uv run --no-sync ruff check $P` | PASS |
| `uv run --no-sync ruff format --check $P` | PASS、115 files |
| `uv run --no-sync mypy` | PASS、115 source files |
| `uv run --no-sync pytest -m ut -q` | PASS、712件（1001 deselected） |
| `uv run --no-sync pytest -m it1 -q` | PASS、590件（1121 deselected） |
| `uv build --no-build-isolation` | PASS、sdist・wheel |
| `bash tools/test-postgres.sh` | PASS、411件（1302 deselected）、106.88秒 |
| `(cd evals/semantic && npm ci --no-audit --no-fund)` | PASS、575 packages |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/*.test.mjs` | PASS、59 registered tests |
| `node tools/check-docs.mjs` | PASS、新規文書・JSONもstage後に確認 |
| `git diff --check` と `git diff --cached --check` | PASS |
| `git diff origin/epic/semantic-quality-improvement -- evals/semantic/cases.json evals/semantic/expectations.json` | PASS、空差分 |

各markerのdeselectedは選択対象外で、SKIPではありません。最終必須ゲートのFAIL・SKIPは0件。
既存依存のdeprecation/type warningはありますが、検証基準を変更していません。

### 偽embeddingによる直接評価

```sh
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --output /dev/shm/dsc-129-acceptance-report.json
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --cases evals/semantic/tuning/cases.json \
  --expectations evals/semantic/tuning/expectations.json \
  --output /dev/shm/dsc-129-tuning-report.json
```

| dataset | 結果 | embedding calls |
| --- | --- | --- |
| 固定62件 | PASS、各回62/62、全26分類100%、全必須ゲートPASS | 183 |
| 調整87件 | PASS、各回87/87、全16分類100%、全必須ゲートPASS | 258 |

両reportは `mode=fixture`, `quality_evidence=false`。ケースとgoldのhashは以下で照合しました。
評価時は実装のcommit前だったため、reportの実行commitは起点、dirtyはtrueです。
reportは本文を含まず、`/dev/shm` のローカル揮発性証跡です。

| ファイル | SHA-256 |
| --- | --- |
| `../cases.json` | `9f703b32ed79ac997320409dd38142324095084ec93164c60ea6b5aca9e50122` |
| `../expectations.json` | `0e979d561be09a45faf019baba285c14605f46ebacc6194f86b5298aa981caa4` |
| `cases.json` | `ea4d2cb88fb5598adfcd5576c9c13b15b2d9e371e97c29878db00271797c31ad` |
| `expectations.json` | `b41b6fe16928b3b8803837888cdbff41e39591a14a8e7e2920a5a50f45180d8a` |

### 外部データのローカル取得

```sh
python3 -I tools/prepare-semantic-tuning-supplements.py \
  --output /dev/shm/dsc-129-supplements-final \
  --nomiracl-per-subset 50 --mkqa-pairs 100
```

PASS、NoMIRACL関連50問・非関連50問／976 passage、MKQA日英100ペア。
取得元・固定revision・カードのライセンス表示・最小形式はREADMEに記録済みです。
本文と変換結果は外部パスだけに置き、コミットしません。
実モデル利用・品質測定・IT2/STは **NOT RUN**（依頼範囲外、#130以降）。

## 初期の失敗と対応

- 調整データ未作成のRed確認: 新規UT7件 **FAIL**。データを作成後、7件PASS。
- 取得変換: 「relevantは最大10 passage」「corpus IDに重複なし」という初期前提で2回 **FAIL**。
  元の追加判定をすべて保持し、同一本文だけ重複排除するよう修正。矛盾する重複は拒否。
  合成UTを追加し、上記の最終取得・変換をPASSまで実施。
- 開発中のruff長行・format・mypy型注釈不足は **FAIL**。修正後、最終lint/format/mypyはPASS。
- 初回PG全試験: **FAIL**（309 passed、1 failed、101 errors）。追加261 schemaの評価後に、
  共有の使い捨てPGが `storage_unavailable` となりました。
  コンテナはcleanupで削除済みのため、OOM等の直接原因は未確認です。
  catalog/WAL増加を既存storage suiteの512 MiBコンテナへ重ねないため、新規評価だけを
  既存 `with-test-postgres.sh` の専用使い捨てPGへ分離。全試験を再実行し411件PASS。
  runnerの資源制限・既存テスト・検索基準を緩めていません。

## 未解決事項と判断

本実装の未解決事項はありません。実モデルのscore分布・接頭辞・モデル・閾値の選定は#130です。
外部データにはCoreの架空Binding・会話citation・記憶の正本がないため、synthetic schemaへ偽装せず、
判定付きquery/passagesと日英questionペアのローカル最小形式を採用しました。
既存schema/report/製品コード/SPEC/ADR・合否基準・検索設定を変更していません。
after_answerの回答破棄は検索CLIの範囲外であり、87件の回答モデル評価を完了したとは扱いません。
