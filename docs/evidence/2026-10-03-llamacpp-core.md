# Coreのllama.cpp接続検証（2026-10-03）

- 対象: PUBLIC FYuki/digital-souls-core, ID 1401730345
- 基点main: `3b41b0c76928ca5d640edbd59567a03f50e12774`
- 実装・実サーバー試験revision: `b8f16bbc819da3f97845baa83962e0fd4c028d7d`
- [Issue #13](https://github.com/FYuki/digital-souls-core/issues/13)、[ADR 0003](../adr/0003-local-llamacpp-provider.md)
- この証跡は上記revisionの後に追加する文書。実試験時のtracked作業treeに変更はなかった。
- Ubuntu/WSL、Python 3.12.3、uv 0.8.22、Node 24.19.0、Docker Compose 5.4.0。
- SDK依存は既存lockのLiteLLM 1.103.2 / OpenAI SDK 2.54.0を維持。

## モデルと実行条件

公式llama.cpp b11347、revision `5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd`、image digest:
`sha256:69019445c94c970496c8f6d6447214b837508162dfe1152768942c51237e3ab7`。
ユーザー所有のGGUFコピーのサイズ7381382048 bytesとSHA-256
`1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606`を確認した。
metadataはgeneral.type=model、architecture=gemma4、file_type=15、48 blocks、物理context=262144。
Ollamaの既存gemma4:12bと同じmodel blob。原本を読み直したりACLを変更したりしていない。
別のmmprojコピーもSHA一致とtype=mmprojを確認したが、text-only試験にはマウントしなかった。

Composeの設定は非root uid/gid、read-only rootfs/model、cap_drop ALL、no-new-privileges、
memory 12g、pids 256、127.0.0.1:18081だけ公開、restart=no。
alias=gemma4-12b、GGUF template、reasoning off / enable_thinking=false、runtime context=4096、
parallel=1、GPU layers=99要求、f16 KV、FA on、8 threads。RTX 4070 Ti SUPER 16 GiB。
Ollamaロード済みモデル0を確認し、既存Whisperを変更せず逐次実行した。
背景GPU負荷を統制しておらず、この試験を性能比較に使わない。

## 実Core→SDK→サーバー

公開Mioriと合成入力のみ。profile transport=llamacpp_chat、model=openai/gemma4-12b、
管理者api_base=http://127.0.0.1:18081/v1。検証用ignored local configのみ送信を許可。
通常応答・toolsはmax_completion_tokens=128、temperature=0。Coreを127.0.0.1:18080で
起動し実HTTPで要求した。timeout試験だけ下流をTestClientにし、上流は実サーバーを使用した。

| 試験 | 結果 |
| --- | --- |
| text | PASS、200、非空content、stop、character=miori、model=gemma4-12b |
| native tool + history | PASS、単一fixture_ping、非空ID、arguments={}、返却messageを無加工再送、同IDの固定結果を確認、追加call 0 |
| tool_choice | PASS、auto/required/名前指定で正しいcall、noneでcallなし |
| tool stream | PASS、deltaからID/名前/arguments={}を復元、finish_reason=tool_calls、DONEあり |
| text stream EOF | PASS、200、DONEあり、errorなし、上流slot idle |
| 下流HTTP切断 | PASS、最初のcontent後に接続を閉じ、上流slot idleへ復帰 |
| timeout | PASS、運用者timeout=0.0001秒で504/provider_timeout、上流slot idle |

toolは実行せず合成定数をテスト側が返した。思考・生成本文・私的会話・認証情報は保存/公開しない。
検証用Coreプロセスを停止し、local configのexternal_send_allowed=falseへ戻した。
llamaコンテナは停止待機へ戻し、Ollamaはサービスを変更せずモデル未ロードを確認した。
コピーと固定imageは保持。既存Whisper/Irodori/PoCの設定は変更していない。

## オフライン・運用境界

全suiteはsocket禁止。UT 18・IT1 167（運用scriptのinert shim 7件を含む）・docs 23がPASS。
実SDK mockはendpoint固定、公開ダミーAuthorization、環境内の合成cloud key不転送、
caller api_base拒否、無加工tool履歴、stream EOF/close/cancel/timeout、Responses bridge拒否を含む。
起動scriptはroot、不明unit、active/activating/failed、model SHA不一致をDocker呼出前に拒否する。
実環境でもOllama active時の起動拒否を確認。Ollama停止後の常用切替はNOT RUN。

初回の品質ゲート・package installはPASSだったが、当初の記録はコマンドの要約だった。
その記録を完全な実行記録とみなさず、下記「文書レビュー修正時の再検証」に、実際に再実行した
完全なコマンド・revision・結果を記載する。初回と再実行のrevisionは区別する。
最終headの正確なCI結果はPRに記録する。初回のtest shimの行長違反は修正して再検証した。
既存Starlette非推奨警告・Pydantic ReadOnly警告は残る。skip/xfail/xpassを合格として扱わない。

人格品質、multimodal、他モデル、他の互換サーバー、他クライアント移行、
systemd常駐・自動再起動、mainマージ、外部公開はNOT RUNまたは範囲外。

## PR #14 独立レビュー後のtransport隔離修正

対象: head `0172e9bedf298374f9743af35461fa52895def8b` への指摘。
固定loopback URLでもSDK既定clientが環境proxyを参照し得たため、ローカルprofileでは
CoreがリクエストごとにHTTPX/AsyncOpenAIを構築してLiteLLMへ渡す。
環境proxyを無視しredirectを追わず、既存の他provider設定・共有clientを変更しない。
応答と専用clientのcloseはAnyIO cancellationからshieldする。

回帰テストはsocket禁止で、実際のCore→LiteLLM→AsyncOpenAI→HTTPX生成経路を通す。
HTTPX transportの送受信メソッドだけを置換し、実際に選択されたpoolが
AsyncHTTPProxyでなくAsyncConnectionPoolであることを検証する。
HTTP_PROXY/HTTPS_PROXY/ALL_PROXY（大小文字）、空NO_PROXY、
DISABLE_AIOHTTP_TRANSPORTの両値、AIOHTTP_TRUST_ENV=trueを合成値で設定した。
text、307 redirect拒否、接続失敗、stream EOF/明示close/task cancel/AnyIO cancel/timeout、
リクエスト間の専用pool分離、他profileが専用clientを作らないことを検証する。
外部proxyへの実送信はしていない。既存stream/tool履歴テストも維持する。

runbookのhealth確認はcold load中の503/接続待ちを上限付きで再試行する方式へ変更。
この修正では実GPUサーバー検証と常用切替はNOT RUN。上記の実サーバー結果は
記載済みrevisionのものであり、この修正後の実サーバー合格とは扱わない。

修正後のローカル結果: UT 18 / IT1 184 / docs tests 23 PASS、skip/xfail/xpass 0。
ruff check/format、mypy、locked sync、sdist/wheel buildを実施。

## transport隔離後の実機再検証

独立再レビューCLEAR後、実装revision
`8475c941f492bb5e817a0c5c10045c8ab3d88c64`（tracked変更なし）で再実行した。
同じ固定image/model設定を用い、公開Mioriと合成入力だけを送信した。
Core TCP 18080 → LiteLLM → 専用HTTPX/AsyncOpenAI → llama.cpp TCP 18081を検証した。

- text: HTTP 200、nonempty、character=miori、model=gemma4-12b、finish=stop。
- tools: HTTP 200、単一fixture_ping、非空ID、引数JSON={}。assistantを変更せず、
  同じtool_call_idの合成結果を返してHTTP 200・結果認識・追加callなし。
- tool_choice none/required/named: いずれもHTTP 200、期待した0/1/1 call。
- tool stream: ID/name/argumentsの再構成、finish=tool_calls、[DONE]を確認。
- text stream: 正常終端[DONE]、errorなし、upstream slot idle。
- 実TCPのdownstream切断: 最初のcontent受信後に切断し、upstream slot idleを確認。
- timeout: TestClient → 実SDK → 実サーバーで504/provider_timeout、slot idle。
  timeout検証のdownstreamはTCPではない。

ツール実行、人格品質評価、multimodalはNOT RUN。応答本文・思考・生ログは保存しない。
検証Coreは終了し、ignored local profileはexternal_send_allowed=falseへ復元した。
専用containerも検証後に停止する。常用切替と自動起動の設定は行わない。

## 文書レビュー修正時の再検証

対象はepic revision `33f14c3237dd6ec92a55cb2da9a1d15661a219fa` と、
この証跡・運用手順だけの未コミット変更。製品コード・tests・lockは変更していない。
Ubuntu側で次を実行した。workspace/toolchain pathはこの検証環境の実際の値。
初回実行を推測で補完したコマンドではない。

```bash
set -euo pipefail
cd /mnt/c/Users/asa/Documents/Codex/2026-10-03/task/core-llamacpp-doc-fixes
../api-toolchain/bin/uv lock --check
../api-toolchain/bin/uv sync --frozen
bash -n tools/start-llamacpp.sh
../api-toolchain/bin/uv run --no-sync ruff check src tests
../api-toolchain/bin/uv run --no-sync ruff format --check src tests
../api-toolchain/bin/uv run --no-sync mypy
../api-toolchain/bin/uv run --no-sync pytest -m ut -q
../api-toolchain/bin/uv run --no-sync pytest -m it1 -q
../api-toolchain/bin/uv build --no-build-isolation
../api-toolchain/bin/uv export --frozen --no-dev --no-emit-project --format requirements-txt > ../llamacpp-docfix-runtime.txt
../api-toolchain/bin/uv venv .package-check
../api-toolchain/bin/uv pip install --python .package-check/bin/python --require-hashes -r ../llamacpp-docfix-runtime.txt
../api-toolchain/bin/uv pip install --python .package-check/bin/python --no-deps dist/digital_souls_core-0.1.0-py3-none-any.whl
.package-check/bin/python -I -c 'from digital_souls_core.api import create_app; assert create_app().title == "Digital Souls Core"'
../node-toolchain/node-v24.19.0-linux-x64/bin/node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs
../node-toolchain/node-v24.19.0-linux-x64/bin/node tools/check-docs.mjs
git diff --check
```

Ubuntu-dogfood側では、次の読取り専用Compose検査を実行した。

```bash
cd /mnt/c/Users/asa/Documents/Codex/2026-10-03/task/core-llamacpp-doc-fixes
export CORE_LLAMACPP_MODEL=/home/asa/llama-compare.mD4N9V/blob-1278394b.gguf CORE_LLAMACPP_UID=$(id -u) CORE_LLAMACPP_GID=$(id -g)
docker compose -f compose.llamacpp.yml config --quiet
docker inspect --format '{{.State.Status}}' digital-souls-core-llamacpp
```

結果はconfig成功、container=exited。停止・起動・sudoは実環境で実行していない。
rollback例は作業用の合成fixture（repo外、docker/sudoを無害なshimへ置換）で、
停止済み・停止失敗・inspect失敗・稼働中・状態不明の5条件を検証した。
停止済み以外ではsudo呼出なし、非ゼロ終了を確認した。実行コマンドは次のとおり。
この補助fixtureはcommitted CI testではなく、公開repoだけで再実行できるとは扱わない。

```bash
python3 /mnt/c/Users/asa/Documents/Codex/2026-10-03/task/verify_llamacpp_rollback_snippet.py
```

再検証結果: 上記コマンドはすべて成功。UT 18 / IT1 184 / docs 23 PASS、skip/xfail/xpass 0。
実GPU推論と常用切替は今回NOT RUN。変更後の最終head・CIは修正PRへ記録する。
