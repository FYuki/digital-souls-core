# 意味検索の独立スライス検証

日付: 2026-10-05 JST（検証時刻: 2026-10-04 23:49〜23:54 UTC）

## 対象と環境

- [Issue #39](https://github.com/FYuki/digital-souls-core/issues/39)、[ADR 0010](../adr/0010-in-process-memory-search.md)（Proposed）。
- 基点main: `c10bd09052dea26af81a7110e2ad1a9808c80236`。
- 実装・テストrevision: `0bb387adfc66f50b2ed31623a1a04540e80a4444`。
- `main → epic/semantic-memory-search → feature/semantic-memory-search`。mainへのマージなし。
- WSL Ubuntuの独立worktree `semantic-memory-search`、Python 3.12.3、uv 0.8.22、Node 24.19.0。
- public `FYuki/digital-souls-core`（repository ID `1401730345`）とorigin URLをpush前に再確認。

開始時および公開前のopen PRは0件、意味検索の重複実装・Issueはなし。関連する既存Issue #24/#30、
ADR 0007/0009、mainの検索・失効実装を確認。`.agents/skills`は存在しません。

## コマンドと結果

すべてPASS。UT/IT1はpytest-socketによりネットワークを禁止し、合成履歴と偽embeddingだけを使用。
`LITELLM_LOCAL_MODEL_COST_MAP=True`を設定し、実LLM・GPU・認証情報は使っていません。

| コマンド | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS。lock変更なし |
| `bash -n tools/start-llamacpp.sh` | PASS |
| `uv run --no-sync ruff check src tests` | PASS |
| `uv run --no-sync ruff format --check src tests` | PASS、49ファイル |
| `uv run --no-sync mypy` | PASS、49ファイル |
| `uv run --no-sync pytest -m ut -q` | PASS、94件 |
| `uv run --no-sync pytest -m it1 -q` | PASS、628件 |
| `uv build --no-build-isolation` | PASS、sdistとwheel |
| `uv export --frozen --no-dev --no-emit-project --format requirements-txt`、独立venvへの`uv pip install --require-hashes`、wheelの`--no-deps` install | PASS |
| 独立venvの`python -I`から`create_app`・`EmbeddingSpace`のimportと生成 | PASS |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS、23件、skip/todo/cancelなし |
| `node tools/check-docs.mjs` / `git diff --check` | PASS。新規文書はstage後にも確認 |

ローカルでは同一venvの実行ファイルを直接使ったコマンドも含みます。
既存依存のStarlette非推奨警告とPydantic TypedDict警告は表示されますが、テスト失敗・skipはありません。
初回の追加テストではfixtureに誤った`memory_excluded` fieldを指定し2件FAIL。既存契約の
`memory_excluded_indices`へ修正後に追加51件と全IT1 628件がPASS。初回のformat/type修正も最終ゲートで解消済みです。

## 検証した境界

- 未注入時の文字列検索互換、異なる語句の偽embedding検索、cosine正値のみ・降順・同点最新順。
- vectorの件数/次元/型/NaN/無限/ゼロ長、不正metadata、巨大finite/subnormal値、選外候補の不正拒否。
- 明示抽出済み記憶だけを候補とし、正本履歴を自動取り込みしない。元Memory・全source・抽出provenanceを維持。
- private/指定発話除外、private解除後の非復活、削除・残存sourceのみの再構築、archive維持。
- Bindingのsubject/client/audience/character全軸分離。
- query/候補認可、各await中のprivate/削除/policy/classifier/embedding/space/scope/store交換、結果認可中の選外source撤回。
- 設定snapshotへの不正なin-place変更も検出。空contextと通常contextのdispatch guard、stream/non-streamの最終分類中撤回でprovider呼出しゼロ。
- 1000候補・256 KiB拒否、15秒timeout設定、内容なしの例外、cancel伝播、意味検索失敗を任意の記憶なし継続に変換しないこと。

独立差分レビューで設定snapshotの共有参照を指摘され、独立コピーへ修正して回帰試験済みです。
最終レビューに未解決の重大指摘なし。これはCodeRabbitの代替ではありません。

## CI・レビューと残る範囲

既存`API checks / api-quality`と`Bootstrap checks / docs-tooling`は全PR対象で、新規テストも既存ゲートに含まれます。
最終headのGitHub CI結果はdraft PRに記録します。work→epicのdraftを維持し、main向けPR/マージは行いません。
CodeRabbitの実レビューはNOT RUN。main gateに必要な手動依頼をこのwork PRで連投せず、既存の頻度制限を維持します。

実embedding adapter・モデル選定・検索精度/速度・IT2/STはNOT RUN。
本スライスはtrusted起動側が注入するプロセス内portであり、任意Python実装の通信やCPU実行をsandboxで制限するものではありません。
vectorは検索呼出し中だけの一時値で、永続index/cacheは追加していません。
Ubuntu-dogfood、GPUサービス、history保存設定、私的DB・実会話、新規有料API/資格情報は使用・変更していません。
