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

## 親レビュー指摘の追試と修正（2026-10-03）

親レビュー対象は `5c8223609ee50bda7e4606e7cec05cfa24734be0` です。
同じlockのPython 3.12.3 / Pydantic 2.11.9 / FastAPI 0.116.1環境で合成回帰を追加し、
修正前に **8 failed / 3 passed** を確認しました。失敗はstream/非stream両方を含みます。

- P1: 同時再試行で先に保存されたreceiptを返すときの再認可漏れ。
  実際に返すreceiptを現在のread policyで再認可します。拒否時も先行記録は変更しません。
- P2: 同じevent-loop tickの切断とprovider完了の競合。
  切断observerが直接cancelし、commit直前にcancel受付点を置きます。
  provider解放→切断と切断→provider解放の両順序で未保存・同request再試行を確認しました。
  二重cancelによる非同期cleanupの中断も避けます。
- P2: 初回schema作成の途中停止。
  DDLとversion設定を単一transactionにしました。turns作成直前・version設定直前に
  子processを`os._exit`で強制終了し、再open後の回復を確認しました。
  未知のversion 0 DBは内容を保持して拒否します。旧部分schemaを自動修復しません。

さらに独立レビューで、切断時に破棄した既存stateless応答のprefetch済みupstreamが
閉じられない問題を検出しました。ASGIへ渡さなかったManagedStreamを明示closeし、
既存のalias/character両経路に回帰テストを追加しました。
最終再レビューに残るblockerなし。reviewer自身の対象3ファイルの実行は **49 passed** です。

最終コード検証revision: `9327349b9da8116a942c7fe63b3bc21d1d066856`。
上記と同じ全必須コマンドを再実行し、以下を確認しました。

| 範囲 | 結果 |
| --- | --- |
| lock確認・frozen sync | PASS、lock変更なし |
| lint・format・mypy | PASS、26 files |
| UT | PASS、28 passed、178 deselected |
| IT1 | PASS、178 passed、28 deselected |
| Node文書テスト・文書検査・diff check | PASS、23 tests |
| sdist/wheel・独立locked install/import | PASS |
| 修正差分の公開前credential/private artifact検査 | PASS |

commit前に観測した切断は保存を抑止します。実ネットワーク切断時刻とASGI通知の到着は
同一とは限らず、commit後の配送失敗ではreceiptを維持します。この場合の同request再試行も
stream/非streamで確認しました。証跡追加は文書のみで、最終headのCIはPR checksで確認します。
epic/main mergeおよびCodeRabbitへの依頼は行っていません。
