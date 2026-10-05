# ローカルembedding adapter・合成評価の検証

日付: 2026-10-05。関連: [Issue #41](https://github.com/FYuki/digital-souls-core/issues/41)、
[ADR 0011](../adr/0011-local-memory-embedding.md)（Proposed）。

## revisionと環境

PR #40のexact head `b9c41d65cee784fb10b82e1202cba992b074b9ab`、両必須CI成功を確認し、
ユーザーの「epicへのPRはCIグリーンで承認して良い」「マージまでして良い」に基づいて通常mergeしました。
epic merge commitは `48322957555fe578e8a73444fcceaec6e0bd99d4`、統合後の
[API CI](https://github.com/FYuki/digital-souls-core/actions/runs/37245678927)と
[文書CI](https://github.com/FYuki/digital-souls-core/actions/runs/37245678913)もsuccessです。
mainは変更していません。

本sliceの実装revisionは `5e5d289f192734b94c9bedc63c42927fefd030b8`（初期実装 `8cdb38f13f998c06877a171b1fd011c261d2e7ec`）。
WSL Ubuntuの独立worktree `local-memory-embedding`、Python 3.12.3 / uv 0.8.22 / Node 24.19.0。
openai 2.54.0、httpx 0.28.1など既存lockを維持し、新規依存を追加していません。

## 必須検証

| 検証 | 結果 |
| --- | --- |
| `uv lock --check` / `uv sync --frozen` | PASS、lock変更なし |
| `ruff check src tests tools/evaluate-memory-search.py` | PASS |
| `ruff format --check src tests tools/evaluate-memory-search.py` | PASS、56ファイル |
| `mypy` | PASS、CLIを含む56ファイル |
| `pytest -m ut -q` | PASS、132件 |
| `pytest -m it1 -q` | PASS、746件 |
| `uv build --no-build-isolation`、hash付きlocked依存の独立venv install、wheel install/import | PASS |
| 固定Nodeのguard付き文書tooling tests | PASS、23件 |
| `node tools/check-docs.mjs` / `git diff --check` | PASS、新規ファイルstage後も確認 |
| `python tools/evaluate-memory-search.py` | PASS、offline偽vector評価 |

pytestはsocket禁止、実SDK/HTTPXのsocket I/Oだけを合成transportに置換しています。
`LITELLM_LOCAL_MODEL_COST_MAP=True`を設定。skip/xfail/0件は既存必須guardが拒否します。
既存Starlette非推奨/Pydantic TypedDictの警告はありますが、最終テスト失敗・skipはありません。
上記は固定venv実行ファイルの直接呼出しを含みます。評価CLIも既存API CIのlint/format/mypyに追加済みです。

## 観測・修正した問題

- SDK typed responseはboolean vectorをfloatへ変換して受理するため、公式`with_raw_response`で取得し
  `http_response.json()`の元JSON型を検証。SDKのpublic raw APIの戻り型相違で生じた初回FAILも修正済みです。
- `OPENAI_CUSTOM_HEADERS`がAuthorization/Host等へ混入する経路を独立レビューで再現。非空ならclient構築前に拒否。
  SDK organization/project/admin/webhookの環境継承を止め、既存local chatでLiteLLM独自organizationが再注入される場合も拒否。
- serviceとadapterのdeadlineが重なるとclose途中へ再cancelが入る問題を再現。内側timeoutをcleanup前に解除し、
  closeは独立TaskとAnyIO/asyncio shieldで完了後にcancelを再伝播。両deadline順・再Task.cancelの回帰を追加。
- local評価modeでも呼出し0件なら品質測定の証拠にならないため、`embedding_call_count`と`quality_evidence=false`を記録。

モデル/次元/応答indexの不一致、異常vector、空入力、proxy/redirect/retry、timeout/cancel、close、
記憶候補の認可とprivate/削除/未抽出履歴の非送信、endpoint/model/次元変更時のguardを確認しました。
既存private・指定発話除外・Binding全軸・由来・再構築の回帰も全IT1に含まれます。
独立最終レビューの関連153件・評価41件がPASS、未解決の重大指摘なし。CodeRabbitの代替とは扱いません。

## 合成評価の結果と限界

[offline JSON report](2026-10-05-memory-evaluation-fixture.json): 5 queries、k=2、Recall@2=1.0、
Precision@2=0.75、MRR@2=1.0、回答不能queryの空結果率=1.0。
これらはfixtureに人手で定義したvectorによるランキング/集計の契約試験です。
`mode=fixture`、`quality_evidence=false`、`backend_identity_verified=false`であり、モデル品質良好の証拠ではありません。
実embeddingモデル、速度、IT2/STはNOT RUN。model digestも運用者の宣言で、モデル真正性の証明ではありません。

通信timeout後も所有接続のclose完了を待つため、呼出し全体が15秒以内に終了する保証ではありません。
外部API、私的会話/DB、モデルDL、GPU、新サービス、Ubuntu-dogfood、history保存設定は使用・変更していません。
PostgreSQL backendは後続の別sliceです。SQLiteデータ移送はユーザーの訂正により不要です。

最終headのGitHub CIリンクはdraft PRへ記録します。mainへはマージせず、CodeRabbitは実レビュー未実施のまま区別します。
