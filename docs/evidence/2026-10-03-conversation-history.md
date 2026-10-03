# 会話履歴第1段階の検証証跡

日付: 2026-10-03。関連 [Issue #18](https://github.com/FYuki/digital-souls-core/issues/18)。
設計: [ADR 0004](../adr/0004-conversation-history.md)、[API](../history-api.md)。
ADR 0003は並行llama.cpp PR用のため番号を分離しています。

## 対象revisionと環境

- Base: `3b41b0c76928ca5d640edbd59567a03f50e12774`（main）。
- 実装・テスト対象: `046712ef3e72bdf9aba081d7403f1d716982667a`。
- この証跡追加commitは文書のみです。最終PR headのGitHub CIはPR checksを正本とします。
- WSL Ubuntu、Python 3.12.3、uv 0.8.22、Node 24.19.0（公式SHA256照合）。
- 作業branch: `feature/conversation-history` → `epic/conversation-history`。
- 合成入力、FakeProvider、SQLite一時DB。GPU・外部推論・私的会話は不使用。

## 必須検証

| コマンド・範囲 | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS、lock変更なし |
| `uv run --no-sync ruff check src tests` | PASS |
| `uv run --no-sync ruff format --check src tests` | PASS、26 files |
| `uv run --no-sync mypy` | PASS、26 files |
| `uv run --no-sync pytest -m ut -q` | PASS、25 passed、168 deselected |
| `uv run --no-sync pytest -m it1 -q` | PASS、168 passed、25 deselected |
| 必須Node reporterによる文書ツールテスト | PASS、23 tests、skip/TODO/cancelなし |
| `node tools/check-docs.mjs` | PASS |
| `git diff --cached --check` | PASS |
| `uv build --no-build-isolation` | PASS、sdistとwheel |
| locked runtime requirementsの独立venvへのhash検証install | PASS |
| wheelの`--no-deps` install、隔離モードでAPI/SQLite adapter import | PASS |

文書テストコマンド:

```sh
node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
```

wheel検証は[CI手順](../../.github/workflows/api.yml)と同じexport・venv・hash付きinstallを使います。
初回buildはローカル検証ツールの仮想環境混入でFAILでした。検証ツールをrepo外へ移し、
上記revisionでsdist/wheel/独立installを再実行してPASSです。
Starletteの既存BlockingPortal非推奨警告とPydanticのReadOnly警告は残ります。

## 独立レビュー

別reviewerがmainとの差分のみを1時間以内で確認しました。初回の2指摘を修正しました。

- P1: ContextSource待機中のexport許可撤回。provider呼出直前の再判定を追加。
- P2: frozenset由来のfingerprint順序変動。正規化と異なるPYTHONHASHSEEDの別process回帰を追加。

再レビューでは残るblockerなし。reviewer自身の
`pytest tests/test_history.py tests/test_conversations.py -q`は **34 passed**。
HTTP切断、streamの分割tool引数、複数tool result、削除と保存の競合も確認しました。
独立レビューはCodeRabbitの代替ではありません。

## 公開前確認と未検証範囲

公開予定12ファイルの内容とdiffを確認し、高確度のcredential形式（private key、GitHub token、
AWS access key、API key）および私的artifactのファイル名を検査して該当なしです。
新規fixtureは合成入力だけです。`SYNTHETIC_SECRET`は拒否テスト用の非秘密sentinelです。
DB、ログ、環境ファイル、私的knowledge、検証ツールをcommitしていません。
この検査は包括的な秘密検出保証ではありません。

実LLM/GPU・IT2/ST・人格品質評価・本番分類器・記憶抽出検索は **NOT RUN / 未実装**。
保存policyは既定拒否で、本番の私的実会話取り込みは有効化していません。
会話streamは完了時配送です。逐次token配送、multi-tenant認証、DB暗号化、backup消去は対象外です。
CodeRabbit依頼は親タスクが調整し、この作業から依頼・main mergeは行いません。
