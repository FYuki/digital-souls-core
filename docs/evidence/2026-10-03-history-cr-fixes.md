# PR #20 レビュー修正の検証（2026-10-03）

## 対象と変更

- Base: `01bafc7d85187e0a9797d68d13fa73f90a9fb08b`
- [Issue #18](https://github.com/FYuki/digital-souls-core/issues/18)、[epic PR #20](https://github.com/FYuki/digital-souls-core/pull/20)
- [stream計算量](https://github.com/FYuki/digital-souls-core/pull/20#discussion_r4172766521):
  累積JSON再serializeと文字列再連結を、断片ごとのescaped UTF-8増分計測とStringIOへ変更。
  tool構造・辞書separatorも計測し、巨大chunkはencode前に拒否。完了時と保存前のexact検証を維持。
- [message上限](https://github.com/FYuki/digital-souls-core/pull/20#discussion_r4172766513):
  合計入力256超は推論前に413/history_limit。独立レビューで発見した256入力後の誤った502も修正。
  入力は既にtool sequence検証済みなので、応答は新規tool名・ID重複・finishの整合を検証する。
- [ADR構成](https://github.com/FYuki/digital-souls-core/pull/20#discussion_r4172766490):
  代替案・影響・Issue/PR/証跡/PoC参照を追加。
- docstring警告は閾値・設定を変更せず、変更対象の公開関数に説明を追加。
  repository全体の80%達成を主張せず、CodeRabbitの再評価は親タスクで確認する。

## 検証

WSL Ubuntu / Python 3.12.3 / uv 0.8.22 / Node 24.19.0、既存lockを変更せず実行。

```text
uv lock --check
uv sync --frozen
uv run --no-sync ruff check src tests
uv run --no-sync ruff format --check src tests
uv run --no-sync mypy
uv run --no-sync pytest -m ut -q
uv run --no-sync pytest -m it1 -q
node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
node tools/check-docs.mjs
uv build --no-build-isolation
```

PASS: lint/format、mypy 31 source files、UT 28、IT1 261、文書23、sdist/wheel、
runtime依存のhash固定独立installと隔離import。新規回帰26件はUnicode/escaping、分割tool引数、
12 toolの構造byte、10,000 tiny chunkの処理量、上限前後、過大chunk、失敗時保存なし、
255/256入力のtext/tool・stream/nonstream、HTTP 413を検証。
線形性は処理したserialize文字数を計測し、実行時間に依存する閾値は使わない。

初回HTTP回帰はTestClientの既定host拒否でFAIL、localhostを明示して修正。
初回型検査2件もテスト側の型注釈・patch対象を修正後PASS。
既存SDK/Starletteの非推奨警告は残る。GPU・実モデル・IT2/ST・分類器はNOT RUN。
合成データのみで検証し、私的会話・secret・生ログを公開差分へ追加しない。
