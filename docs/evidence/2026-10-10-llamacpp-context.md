# llama.cpp context拡張のVRAM・速度実測

2026-10-10、[Issue #147](https://github.com/FYuki/digital-souls-core/issues/147)。
外部Agentのsystemとtoolsがcontext 4096を超えるため、2026-10-10のユーザー決定に従い、
context 8192・16384・32768とK/Vのf16・q8_0を実測しました。
**context 32768、K/Vともf16を選択**します。以下は合成負荷の容量・速度確認です。
OpenClaw実接続の再受入・IT2・STは **NOT RUN** です。

## revisionと環境

- 起点・測定時commit: `0e0cd565778948a58eb089f1ed6566224ef2c785`（cleanな`infra/147-llamacpp-context`）。
- 設定・文書のrevisionは本書を含むcommitです。最終SHAは実装担当の引継ぎ報告で特定します。
- embedding定義の参照revision: `69e44f58c0bfd3676478851d1ab73dd184bd8eaf`、
  `origin/epic/semantic-quality-improvement:compose.llamacpp.yml`を読み取りコピー。
- GPU: NVIDIA GeForce RTX 4070 Ti SUPER、16376 MiB、driver 591.86、WSL Ubuntu。
- UID/GIDは `id -u` / `id -g`で現在ユーザーから取得。
- 両サービスのimage: `ghcr.io/ggml-org/llama.cpp@sha256:69019445c94c970496c8f6d6447214b837508162dfe1152768942c51237e3ab7`。
- 測定開始: `2026-10-10T11:05:25.142555+00:00`、停止確認: `2026-10-10T11:10:58.454039+00:00`。

| モデルファイル | bytes | SHA-256 |
| --- | --- | --- |
| `gemma4-12b.gguf` | 7381382048 | `1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606` |
| `bge-m3-q8_0.gguf` | 634553760 | `aa473d51f451a22f0fcf39ba3330c14bed38a385712b1113440f69df4047a173` |

両ファイルを今回も読み取りでhash計算しました。Gemmaは[既存証跡](2026-10-03-llamacpp-core.md)・
[ADR 0003](../adr/0003-local-llamacpp-provider.md)と一致します。bge-m3も参照branchの固定値と一致します。

## 隔離と測定方法

- リポジトリ外の一時Compose、project `dsc147-bench`、containers `dsc147-gemma` / `dsc147-bge-m3`、
  loopback ports 18181 / 18182を使用。モデルはread-only bind、create_host_path=false。
- Gemmaのサービス定義は起点のComposeをコピーし、測定用の名前・ポート以外は
  ctx-sizeとcache-type-k/cache-type-vだけを変更。image、非root、read_only、cap_drop ALL、
  no-new-privileges、12g memory、pids 256、64MiB tmpfs、flash-attn on、parallel 1、
  gpu-layers 99、fit off、threads/threads-batch 8、cache-ram 0、no-warmup、reasoning offを維持。
- bge-m3は参照branchのembedding定義をコピー。ctx/batch/ubatch 2048、embeddings、pooling cls。
  全構成を通じて起動し、構成ごとに合成埋め込み要求を1回送って1024次元の成功を確認。
- 各要求はCoreを経由せず、`/v1/chat/completions`へ直接送信。
  `/apply-template`後の`/tokenize`（add_special=true、parse_special=true）で入力tokenを数え、
  応答usageと一致することを確認。公式の[固定revisionのserver API説明](https://github.com/ggml-org/llama.cpp/blob/5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd/tools/server/README.md)を参照。
- 通常: 348 prompt tokens、出力128 tokens。ほぼ満杯: contextの約90%、出力64 tokens。
  OpenClaw相当の形: 合成system + function tools 12個 + user、5493 prompt tokens、出力128 tokens。
  全6構成で各種3回、計54要求。実際のOpenClawの設定・文面・toolsを複製したものではありません。
- temperature=0、seed=147、cache_prompt=false、ignore_eos=true、非stream。
  各応答のcache_n=0と指定出力token数を確認。生成内容の品質・tool実行ループは判定しません。
- 同じbge-m3同時起動で4096/f16の通常要求3回も参考測定。
  4096の満杯要求・tools要求は **NOT RUN**。
- 起動前からGemma停止まで、nvidia-smiを目標250ms間隔で採取。
  全体usedの観測最大値を採用。増分は両モデル停止時の基準3252 MiBを引いた値です。
- 各構成の実行を独立した1700秒timeout（TERM後30秒でKILL）に分割。
  実測の最長構成は57.63秒で、各コマンド30分以内です。
- 合成入力のみ。既存コンテナ・他worktree・main checkout・モデルファイルを変更していません。

## VRAM基準と外部負荷確認

- 両モデル停止時の基準: **3252 MiB**（`2026-10-10T11:05:25.142537+00:00`）。
- bge-m3起動・埋め込み後: **3953 MiB**。
- 構成直前とGemma停止後のbge-m3のみの状態を、この基準+1024 MiBで監視。
  ロード後の各要求完了時にも、ロード時から+1024 MiB超の増加を停止条件としました。
  停止条件に該当する増加はありませんでした。Windows側プロセスのVRAMを個別には帰属できず、
  見える全体値を比較しています。全体最大値には背景のGPU使用も含めています。

| context | K/V | 起動前（bge-m3込み）MiB | Gemma停止後（bge-m3込み）MiB | samples | 採取間隔中央値 / 最大（秒） |
| --- | --- | --- | --- | --- | --- |
| 4096 | f16/f16 | 3956 | 3966 | 40 | 0.252 / 0.422 |
| 8192 | f16/f16 | 3965 | 4261 | 129 | 0.252 / 0.419 |
| 8192 | q8_0/q8_0 | 4070 | 4072 | 131 | 0.253 / 0.440 |
| 16384 | f16/f16 | 4096 | 4108 | 157 | 0.251 / 0.438 |
| 16384 | q8_0/q8_0 | 4182 | 3863 | 158 | 0.254 / 0.428 |
| 32768 | f16/f16 | 4376 | 4230 | 220 | 0.254 / 0.446 |
| 32768 | q8_0/q8_0 | 4370 | 4327 | 229 | 0.252 / 0.411 |

採取エラーは0件です。両モデル停止後は3716 MiB（基準+464 MiB）でした。

## 6構成の結果

速度は各3回の中央値、単位token/s。`prompt / gen`はそれぞれ
`timings.prompt_per_second` / `timings.predicted_per_second`です。
起動失敗・OOM・要求失敗はありませんでした。PASSはHTTP応答・実token数・timings・cache非再利用の確認です。

| context | K/V | 全体VRAM最大 MiB | 基準から増分 MiB | 通常 prompt / gen | ほぼ満杯 prompt / gen | tools prompt / gen | 起動 | 要求 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 8192 | f16/f16 | 12253 | 9001 | 2325.19 / 65.20 | 3365.83 / 61.05 | 3121.04 / 60.50 | PASS | PASS 9/9 |
| 8192 | q8_0/q8_0 | 12051 | 8799 | 2215.25 / 60.85 | 3348.05 / 58.60 | 3236.71 / 59.20 | PASS | PASS 9/9 |
| 16384 | f16/f16 | 12452 | 9200 | 2266.81 / 63.54 | 3393.62 / 60.18 | 3095.05 / 60.99 | PASS | PASS 9/9 |
| 16384 | q8_0/q8_0 | 12044 | 8792 | 2200.55 / 60.98 | 3267.23 / 57.43 | 3222.81 / 58.90 | PASS | PASS 9/9 |
| 32768 | f16/f16 | 12913 | 9661 | 2230.03 / 63.76 | 3100.71 / 57.67 | 3135.12 / 60.11 | PASS | PASS 9/9 |
| 32768 | q8_0/q8_0 | 12337 | 9085 | 2183.10 / 60.73 | 2989.87 / 52.69 | 3136.36 / 58.16 | PASS | PASS 9/9 |

| context | K/V | 通常 prompt_n / gen_n | ほぼ満杯 prompt_n / gen_n | tools prompt_n / gen_n | wall中央値（通常 / 満杯 / tools、秒） |
| --- | --- | --- | --- | --- | --- |
| 8192 | f16/f16 | 348 / 128 | 7369 / 64 | 5493 / 128 | 2.118 / 3.248 / 3.883 |
| 8192 | q8_0/q8_0 | 348 / 128 | 7369 / 64 | 5493 / 128 | 2.262 / 3.297 / 3.872 |
| 16384 | f16/f16 | 348 / 128 | 14730 / 64 | 5493 / 128 | 2.173 / 5.429 / 3.888 |
| 16384 | q8_0/q8_0 | 348 / 128 | 14730 / 64 | 5493 / 128 | 2.268 / 5.642 / 3.890 |
| 32768 | f16/f16 | 348 / 128 | 29486 / 64 | 5493 / 128 | 2.165 / 10.677 / 3.879 |
| 32768 | q8_0/q8_0 | 348 / 128 | 29486 / 64 | 5493 / 128 | 2.262 / 11.112 / 3.959 |

参考4096/f16: 起動PASS、通常3/3 PASS、VRAM最大11913 MiB・増分8661 MiB。
通常prompt/gen中央値は2212.19 / 64.54 token/s、wall 2.137秒。

## 選択と変更範囲

- 上限は16376 MiB × 90% = **14738.4 MiB**。全6構成が起動・3種各3回成功・VRAM上限を満たす。
- 最大のcontext **32768** を選び、同contextの比較では品質劣化を避ける指定に従って **f16/f16** を優先。
- 選択構成の最大12913 MiBはGPU容量の78.9%。GPU全体に3463 MiB、90%上限まで1825.4 MiBの余裕。
- 通常生成63.76 token/sは4096/f16の64.54 token/sの98.8%。
  全6構成の通常生成速度も基準の半分以上で、指定の速度停止条件に該当しない。
- Composeはctx-sizeの値1行だけを4096→32768へ変更。KV型・行順・他サービスは変更しない。
- 運用文書を新contextと実測VRAMへ同期。ADR 0003のStatusと本文を保持し、冒頭に置換注記のみ追加。
- 過去の証跡の4096は当時の記録として保持。製品コード・Core byte budget・1 MiB上限は変更しない。

## 生データと再集計

以下はリポジトリ外のローカル一時成果物で、再起動時に消える可能性があります。
監督担当は必要なら再起動前に回収してください。JSONには構成・要求種別・試行ごとのtimings、
usage、wall time、token数、成否、250msのVRAM時系列、起動・停止確認を保存しています。
要求・応答の本文はreportへ含めません。別ファイルの入力とcontainer logは合成データのみです。

| 成果物 | ローカルpath | SHA-256 |
| --- | --- | --- |
| report.json | `/dev/shm/dsc147/report.json` | `cfded45fbd5fcbd9661b4b480e411a0b0b4b5036633a6da83033e53a1c8f2a4a` |
| bench.py | `/dev/shm/dsc147/bench.py` | `e8ad36b0f013ae3fe2399bd77881f427e0299b2ce6551b237909601af757171f` |
| summarize.py | `/dev/shm/dsc147/summarize.py` | `7b070d5adb5a75f1d59661436a1703b52a9a3fac7f636e9a1ea5f535ae6b333e` |
| summary.json | `/dev/shm/dsc147/summary.json` | `7d9911d3c87b0a63556eafa256b8454a2e9f438ba1b1660e72b651097ba606ee` |
| embedding-source.yml | `/dev/shm/dsc147/embedding-source.yml` | `b79dd006f34bb25f57ebb75a5b112825b06d0473c6478a8b19043b984a0f217e` |

一時Compose: `/dev/shm/dsc147/compose.yml`（最後の32768/q8_0構成を保持）。
要求入力: `/dev/shm/dsc147/input-<ctx>-<kv>-<kind>.json`。
ログ: `/dev/shm/dsc147/logs-<ctx>-<kv>.txt`（失敗なし）。

```sh
python3 /dev/shm/dsc147/bench.py init
# 4096/f16は参考通常要求のみ。続いて6構成を各々独立コマンドで実行する。
timeout --signal=TERM --kill-after=30s 1700s python3 /dev/shm/dsc147/bench.py run --ctx 8192 --kv f16
# 同様に8192/q8_0、16384/f16、16384/q8_0、32768/f16、32768/q8_0。
python3 /dev/shm/dsc147/bench.py cleanup
python3 /dev/shm/dsc147/summarize.py
```

`init`は既存report・同名containerを上書きしないため、再測定時は新しい一時場所・名前で隔離します。

## コンテナ停止確認

`2026-10-10T11:10:58.454039+00:00` に `docker ps -a` のproject限定結果を確認しました。

```text
dsc147-gemma	Exited (0) 14 seconds ago
dsc147-bge-m3	Exited (0) Less than a second ago
```

各構成のGemma停止もexitedです。禁止対象の既存3コンテナについて、測定前後の
container ID・状態exited・StartedAt・FinishedAtがすべて一致しました。
既存コンテナへのstart/stop/rm/recreateは実施していません。

## ゲートと制約

Node 24.19.0の指定固定toolchainを使用しました。Tは手元の`history-stage1-tools`の絶対pathに設定します（Tを先にexport）。

```sh
export T=/path/to/history-stage1-tools
export PATH=$T/bin:$T/node/bin:$PATH
export TMPDIR=/dev/shm
```

| ゲート | 結果 |
| --- | --- |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS、27 registered tests、SKIP/TODO/cancelなし |
| `node tools/check-docs.mjs` | PASS |
| `git diff --check` | PASS |
| `CORE_LLAMACPP_MODEL=/nonexistent CORE_LLAMACPP_UID=1 CORE_LLAMACPP_GID=1 docker compose -f compose.llamacpp.yml config -q` | PASS |
| UT / IT1 / PostgreSQL | NOT RUN（製品コード変更なし） |
| IT2 / ST | NOT RUN |
| OpenClaw → Core → Gemma実接続再受入 | NOT RUN（別スレッド担当） |
| GitHub CI / push / PR / merge | NOT RUN（監督担当） |

合成の反復入力は実際のAgent要求の多様性や品質を保証しません。ignore_eosは速度計測用です。
非streamの直接サーバー負荷であり、Core経由の互換性・実tool往復・長文理解・人格品質・
長時間連続運用を今回のPASSへ含めません。背景GPU使用は変動し、将来の余裕は起動前に再確認が必要です。
最大値は250ms採取の観測値で、サンプル間の短いピークは捕捉できない可能性があります。
