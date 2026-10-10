# 意味検索の調整専用データ

Issue #129 / Epic #124。2026-10-10 のユーザー決定 Q3・Q5 に従い、閾値・タスク接頭辞・
embedding モデル選定の調整に使うデータを、[合否判定用の固定62ケース](../README.md)から分離します。
この87件や外部補助データの結果を、62ケースの品質合格として使いません。
モデル比較・実モデル実行は #130、採用判断の ADR は #131 です。

[実装時の品質ゲート・fixture評価・初期失敗の記録](VALIDATION.md)。

## 合成ケースの分類

| category | 件数 |
| --- | --- |
| synonym | 10 |
| paraphrase | 10 |
| cross_language | 24 |
| unrelated | 20 |
| threshold | 12 |
| private | 1 |
| excluded | 1 |
| deleted_source | 1 |
| deleted_memory | 1 |
| binding_character | 1 |
| binding_subject | 1 |
| binding_client | 1 |
| after_search | 1 |
| after_answer | 1 |
| epoch_change | 1 |
| equivalent_order | 1 |

合計 **87件**。架空のネモラ / Nemora、別Bindingのヴェルダだけの合成です。
機器の校正・工業試験・資料保存・ホログラム展示の保守を新しい題材にし、62ケースの文・人物・
物語を流用・言い換えしていません。query・記録全文の集合を横断し、完全一致・NFKC一致・
NFKC→casefold一致がないことを [UT](../../../tests/test_semantic_tuning_cases.py) で確認します。
Fact更新が追加された場合も、その保存文を比較対象に含みます。題材の非流用は全文を確認した判断であり、
文字列非一致だけで意味上の独立性が証明されるとは扱いません。

- cross_language は記憶が日本語・質問が英語12件、記憶が英語・質問が日本語12件。
  各ケースの紛らわしい記録も記憶側の言語です。
- synonym・paraphrase は各10件。改善による既存能力の悪化を検出します。
- unrelated は20件すべて該当なし。同じ人物・同じ設備の別属性や別部材の記録を2件入れ、
  分野の類似だけで回答できない問いに候補が残るかを測ります。
- threshold は答えのある6件と該当なし6件。同じ人物・同じ装置の紛らわしい別事実も入れます。
  偽vectorの対象候補は関連度0.5401〜0.541と0.539〜0.5399、別候補は0.53です。
  意味上の期待値を先に固定し、偽vectorで現行閾値の両側を確認します。
  実モデルの関連度がこの範囲になるという主張ではありません。
- privacy・Binding・出典失効と同等帯の分類は各1件です。after_answer の回答破棄自体は
  検索CLIの採点範囲外で、検索・dispatch時点までを確認します。

[cases.json](cases.json) は既存と同じ入力schema 1 / synthetic、
[expectations.json](expectations.json) はgold schema 2。goldを入力へ混ぜません。
`load_evaluation_cases` で全件検証します。4次元の有限・非ゼロ偽vectorは同一本文で同一です。
本番候補20・最大5・閾値0.54・同等帯0.002・`last_user_mentioned_at DESC` と、
必須ゲート・各回各分類90%の既存ハーネスは変更していません。
reportの `passed` は選んだ調整データに対するハーネス結果です。品質受入を表しません。

## fixture 実行

リポジトリルートから実行します。実モデル・GPUは使いません。

```sh
T=/home/asa/dev/digital-souls-evidence/history-stage1-tools
export PATH=$T/bin:$T/node/bin:$PATH TMPDIR=/dev/shm
uv sync --locked
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --cases evals/semantic/tuning/cases.json \
  --expectations evals/semantic/tuning/expectations.json \
  --output /dev/shm/semantic-tuning-report.json
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --output /dev/shm/semantic-acceptance-report.json
```

入力schema・report schemaを増やさず、reportの `case_version.cases_sha256` と
`expectations_sha256` でデータを識別します。87件のIDは `tuning-` で始まり、62件と区別できます。
比較時は対象ファイルの `sha256sum` と照合してください。
CIの `postgres-storage` が実行する [PostgreSQL試験](../../../tests/test_postgres_semantic_evaluation.py)に、
87件×3回の必須fixture試験を追加しています。0件・skipを成功にしません。
fixtureの成功は実モデル品質・実環境IT2/STの合格ではありません。

## ローカル限定の外部補助データ

取得先・変換先は管理外の専用空ディレクトリにします。データ本体・質問文・本文・変換結果はコミットしません。

[取得・変換スクリプト](../../../tools/prepare-semantic-tuning-supplements.py)は標準ライブラリだけを使い、
固定revisionの TSV / JSONL gzip とデータセットカードを HTTPS で取得します。
remote Python・`trust_remote_code`・pickle・展開archive・外部コマンドは実行しません。
取得ファイルごとに SHA-256・URL・サイズ、取得日時と選択件数をローカル `manifest.json` に残します。
圧縮入力・展開後・1行のサイズを制限し、失敗時には非0終了・manifest未作成となります。
途中ファイルは完了データとして使わず、再実行には新しい空ディレクトリを指定します。
Git tree内・非空ディレクトリ・出力先symlinkを拒否します。

```sh
# repoルート（信頼するコードの側）から実行。出力先は新しい専用パスにする。
python3 -I tools/prepare-semantic-tuning-supplements.py \
  --output /dev/shm/dsc-tuning-supplements \
  --nomiracl-per-subset 50 --mkqa-pairs 100
```

`/dev/shm` は揮発性です。保持する場合もGit管理外の専用パスを引数で渡し、
そのディレクトリへ移動してPythonを実行しません。実モデルを呼ぶ機能はありません。

### 取得元・版・ライセンス確認

2026-10-10 02:02:07 UTC に取得・変換 **PASS**。モデルによる利用・測定は **NOT RUN**（#130）。
選択は固定ファイルの先頭順で、結果による選び直しはしていません。

| データ | 固定revision | 使った件数 | カードで確認したライセンス |
| --- | --- | --- | --- |
| NoMIRACL / japanese / dev | `ecd08778d0426a5ca28ac99763b0c9ddc2c78e68` | relevant 50問 + non_relevant 50問、判定付きpassage 976件（unique 976） | Apache-2.0 |
| MKQA / ja-en | `f964fe1bac4d580cee3d4928572df1f676f8e656` | 日英100ペア（原本10,000行をダウンロードし整合性確認） | データ CC BY-SA 3.0 Unported |

- NoMIRACL の[固定版カード](https://huggingface.co/datasets/miracl/nomiracl/blob/ecd08778d0426a5ca28ac99763b0c9ddc2c78e68/README.md)と
  [日本語ファイル](https://huggingface.co/datasets/miracl/nomiracl/tree/ecd08778d0426a5ca28ac99763b0c9ddc2c78e68/data/japanese)。
  `topics/dev.{relevant,non_relevant}.tsv`、`qrels/dev.{relevant,non_relevant}.tsv`、`corpus.jsonl.gz` を取得します。
  カードのライセンス表示は Apache-2.0、passage は Wikipedia由来と説明されています。
  [MIRACL corpusカード](https://huggingface.co/datasets/miracl/miracl-corpus/blob/main/README.md)も確認しました。
  本文の再配布条件を新たに判断したものではなく、本文はローカルにのみ置きます。
- MKQA の[固定版README（データセット説明・License）](https://github.com/apple-aiml-research/ml-mkqa/blob/f964fe1bac4d580cee3d4928572df1f676f8e656/README.md)と
  [圧縮データの取得URL](https://raw.githubusercontent.com/apple-aiml-research/ml-mkqa/f964fe1bac4d580cee3d4928572df1f676f8e656/dataset/mkqa.jsonl.gz)。
  コードのLICENSEとデータのCC BY-SAを区別しています。

NoMIRACL の relevant qrels には10件を超える追加の判定済みpassageがあり、すべて保持します。
corpusの同一ID・同一title/textの繰り返しはまとめ、矛盾する繰り返しは拒否します。
初期の「各query最大10件」「corpus ID重複なし」という変換前提では FAIL したため修正し、
追加判定・同一重複・矛盾重複の合成UTを追加して上記の最終取得・変換を再実行しました。
本文・質問文の例はこの文書やテストに転記していません。

### #130 へ渡す最小形式

外部データは合成schemaの `dataset_type=synthetic`、架空Binding、会話出典へ偽装しません。
NoMIRACL は検索queryと判定済みpassage、MKQA は翻訳質問のペアであり、
本人の記憶・会話・citation・正本を持たないため `load_evaluation_cases` 用には変換していません。
別のローカル JSONL schema 1 として次を出力します。

| ローカルファイル | 各行のフィールド | #130で測れること・制約 |
| --- | --- | --- |
| `nomiracl-ja.jsonl` | `schema_version`, `dataset=nomiracl-ja`, `source_id`, `subset`, `query`, `passages`（`id`, `title`, `text`, `relevance=0/1`） | 日本語queryと関連／非関連passageのembedding score分布。qrelsラベルを保持。queryの長さ・本文量はCoreの制限に合わせていないため、そのまま本番検索CLIへ渡さない。 |
| `mkqa-ja-en.jsonl` | `schema_version`, `dataset=mkqa-ja-en`, `source_id`, `ja`, `en` | 同じquestionの両言語を両方向で比較。回答・passage・検索goldを含まないため、記憶検索の合否には使わない。 |
| `manifest.json` | 取得日時、版、出典URLと各原本SHA-256・サイズ、件数 | 本文を含まない取得証跡。データセットカードは同じローカルディレクトリに保持。 |

#130はこの最小形式を読み、合成87件の調整を補助します。外部本文を含む出力・変換結果もコミットしません。
