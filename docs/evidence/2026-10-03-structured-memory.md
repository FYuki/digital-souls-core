# 構造化出力の合成データ検証（2026-10-03）

## 対象

- base: `0cc586a551090becde48277eaabae1afa7afc84f`
- 実機・独立レビュー対象コード: `7c6d9c633c77c4bee47a38f6b3d4ff29f48735ea`
- Python 3.12.3、uv 0.8.22、Node 24.19.0。依存はuv.lock固定。
- llama.cpp b11347 / `5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd`
- image: `sha256:69019445c94c970496c8f6d6447214b837508162dfe1152768942c51237e3ab7`
- Gemma4 12B Q4_K_M、context 4096、alias `gemma4-12b`
- GGUF SHA-256: `1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606`

## 実機の小規模比較

追加予算8回を使用。変更前の抽出器1回はコードブロックを返し`memory_extraction_failed`。変更後は2026-10-03 20:30:59–20:31:06 UTCに7回を直列実行し、全てコードブロックなし・strict schema有効・finish=stopだった。各リクエストは12秒上限、実測0.839–1.503秒。

通常入力は創作した茶の嗜好、機微入力は架空人物の健康情報。私的会話・knowledgeは使用していない。合成historyから現在の承認versionを持つpending jobをテスト用に作り、production `MemoryService.run`（入力分類・抽出・出力分類・返却分類の4回）、`search`（2回）、健康情報のpolicy判定（1回）を通した。新規`extract`入口にある重複した事前分類は呼出予算のため省略している。その入口まで実機で通した検証ではない。

抽出候補1件・検索結果1件、出典整合確認成功。通常の分類5回はNOT_SENSITIVE、健康情報1回はSENSITIVEとなり拒否した。出典削除後の検索は空。DBはGit外の一時領域（directory 0700 / DB 0600）で作成・削除した。生出力・内部思考・秘密値を証跡に残していない。

実リクエストはLiteLLM/OpenAI SDK経由で既存loopback endpointだけへ送った。プロセス内だけで無効proxyを指定し、環境proxyを使わないことを確認。socket監査はlocal接続7、外部接続0。llama/Whisperの起動時刻とimageは前後で同じ。llama開始時刻は2026-10-03T11:53:31.998122844Z。終了時GPU使用量11787/16376 MiB、利用率0%。手動Coreの18080は待受なしであり、起動・停止・設定変更していない。

## 自動検証と独立レビュー

追加14テストは両adapterの実SDK→HTTP境界でschema送信、未対応HTTP400、fenced/不正出力、制約なし再試行の不在を確認する。schema・契約・SDK・旧provenance変更で保留job/検索が拒否され、明示的な新規抽出が進むこと、公開入力へのresponse_format追加が拒否されることも確認した。

独立レビューはコード差分を対象に指摘なし。レビュアー自身が関連176テストとdiff checkを実行して成功した。全体検証はUT 30件、IT1 568件、文書検証ツール23件成功。ruff check/format、mypy（45 files）、lock整合、frozen sync、sdist/wheel build、別venvへのhash検証付き依存導入・wheel導入・isolated importが成功した。最終headのCI結果はPR本文に記録する。

主要コマンド: `uv lock --check`、`uv sync --frozen`、`uv run --no-sync ruff check src tests`、`uv run --no-sync ruff format --check src tests`、`uv run --no-sync mypy`、`uv run --no-sync pytest -m ut -q`、`uv run --no-sync pytest -m it1 -q`、`node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs`、`node tools/check-docs.mjs`、`uv build --no-build-isolation`。

## 制限

これは固定されたモデル・server・少数の合成入力の互換性smokeであり、人格品質、機微情報の網羅的検出率、他モデル/providerの対応は保証しない。実機でrebuildや新規extract入口全体を実行した証跡でもない。これらの制御境界は合成UT/ITで検証する。実会話の自動取り込み、既存承認の更新、外部送信fallbackは有効化していない。設計は[ADR 0008](../adr/0008-managed-structured-output.md)を参照。
