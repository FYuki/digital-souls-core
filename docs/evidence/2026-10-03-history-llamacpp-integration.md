# 会話履歴とllama.cpp mainの統合検証

日付: 2026-10-03。[Issue #18](https://github.com/FYuki/digital-souls-core/issues/18)、
[作業PR #19](https://github.com/FYuki/digital-souls-core/pull/19)。

## 対象revision

- 取り込みmain: `ae0fa863b28fc79f80ab3206dd97d51734996524`（PR15統合済み）。
- 直前の履歴head: `cd039186215c0a00c733f74581d5d00dd012bb06`。
- 通常merge: `622f9dc8d2abd7cfe5da94769c10b96bf994edc6`。衝突なし。
- 最終コード検証: `50be9e9057d503653a41fdf2dcb8f2146a711fb7`。
- 専用epicはmainへfast-forward mergeし、作業branchへ通常mergeしました。
  rebase・force push・他worktreeの変更は行っていません。

## 統合差分

`character.py`、`provider.py`、API CI workflow、llama.cpp起動scriptはmainと同一です。
追加した実装差分は、SDK経路の既存receiptを再試行できるようfingerprintの既定値を正規化する
4行だけです。mainで追加された`transport=sdk`と`api_base=None`は従来の経路を変更しないため、
以前のfingerprintを維持します。llama.cpp経路ではtransport・endpointを引き続き照合対象とします。
統合前revisionから固定したfingerprintの再試行テストは補正前にFAIL、補正後にPASSです。

新しい結合テストは実際のLiteLLM/OpenAI SDKとllama.cpp adapterを使用し、socket I/Oだけを
合成HTTP応答へ差し替えます。履歴のtext・tool往復・stream・tool stream・timeout・cancel、
DB再open後の再試行、transport/stream close、loopback固定、dummy認証、endpoint変更の識別を検証します。
GPU・実サービス・実モデル・私的会話は使用しません。

## 検証結果

WSL Ubuntu、Python 3.12.3、uv 0.8.22、Node 24.19.0、変更のないuv.lockを使用しました。
コマンドは[開発規約](../../CONTRIBUTING.md)および[API CI](../../.github/workflows/api.yml)と同じです。

| 範囲 | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS |
| `bash -n tools/start-llamacpp.sh` | PASS（サービス起動なし） |
| ruff lint / format / mypy | PASS、30 files |
| `pytest -m ut -q` | PASS、28 passed、235 deselected |
| `pytest -m it1 -q` | PASS、235 passed、28 deselected |
| Node必須文書テスト | PASS、23 tests |
| 文書検査 / diff check | PASS |
| sdist / wheel / 独立locked install・import | PASS |
| 公開差分のcredential/private artifact検査 | PASS |

stateless/profile/providerと、既存履歴のprivacy・原子性・切断・所有権の回帰を全件実行しました。
独立レビューは統合差分だけを対象にし、追加blockerなし。reviewerの対象テストは **9 passed**。
受け入れ済みPR15全体を再レビューしたという意味ではありません。

従前の設計・指摘修正は[履歴保存証跡](2026-10-03-conversation-history.md)を参照してください。
依存由来の既知警告は残っています。実LLM/GPU、IT2/ST、人格品質は **NOT RUN**。
分類器・記憶抽出検索は未実装、私的実会話の自動取り込みは既定拒否です。
CodeRabbit依頼とmainへのmergeはこの統合作業の対象外です。
