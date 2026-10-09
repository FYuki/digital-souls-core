# 上位5件への包含による意味検索・回答の実モデル再評価

日付: 2026-10-09。対象: FYuki/digital-souls-core、`fix/120-top5-criteria`。
実行commit: `20d9edbaa9905c0e86e8d9b1c8cfaa5eddb85788`、検索・回答とも **dirty=false**。
後続commitは本文を含まないreportと文書同期だけです。

正本: [Issue #120](https://github.com/FYuki/digital-souls-core/issues/120)、
[Epic #111 V5/V7](https://github.com/FYuki/digital-souls-core/issues/111)、
[ADR 0023の置換注記](../adr/0023-semantic-evaluation-contract.md)。
[前回証跡](2026-10-09-semantic-real-model-evaluation.md)の結果は保持します。
公開report: [検索](2026-10-09-semantic-real-model-retrieval-top5.json)、
[回答](2026-10-09-semantic-real-model-answer-top5.json)。

## 基準の変更と固定条件

2026-10-09のユーザー決定「上位5件の中に、1位にあるべき記憶が含まれていれば合格。
順序の一致は求めない」を適用しました。top-1はgoldの `expected_order` があれば先頭、
なければ `relevant_ids` の先頭、空なら該当なしです。全62ケースのUTで導出規則と
非空 `dispatch.memory_ids[0]` との一致を確認しました。

検索では `top_one` を両modeの必須ゲートとし、`expected_order` 全順序一致はfixtureのみです。
実vectorは偽vectorと同じ同等帯になる保証がないため、sort実装の検証は決定論的fixtureへ残します。
検索fixtureの62×3はすべてPASSし、各回のequivalent-band-orderは
`tie-a → tie-b → tie-c → tie-d → tie-null` の全順序と `expected_order=true` を確認しました。
回答fixtureも62×3すべてPASSです。fixtureは道具の検証であり品質受入ではありません。

回答dispatchはgoldのvalid一致を維持し、trueなら送信上位5件へのtop-1包含、
falseならID空を要求します。top-1なしならID照合なし、no_memoryの空contextは維持します。
禁止IDは引き続き拒否します。余分な非禁止候補や順序差だけではFAILにしません。

検索品質の `relevant_ids ⊆ 返却`、必須/禁止事実、privacy・Binding・失効・正本検証、
閾値未満混入、検証不能な記憶への代替禁止、no_match/no_memory、lifecycleは変更しません。
ケース・gold・キャラクター・カード・プロンプト・依存・検索設定・server設定も変更しません。
各回各分類90%以上と全必須ゲート合格を要求し、平均で相殺しません。

## 環境とモデル

Python 3.12.3、uv 0.8.22、Node 24.19.0、npm 11.17.0、promptfoo 0.117.2、
better-sqlite3 13.0.3、OpenAI SDK 2.54.0、TMPDIR=/dev/shm。
GPUはRTX 4070 Ti SUPER、16376 MiB、Linux driver 590.57 / host driver 591.86、CUDA表示13.1。
起動前は2998 MiB使用、GPU 0%、nvidia-smiの推論process表示なし。
psでも他のllama-server / ollama / whisper / irodori推論processは検出しませんでした。
両評価コンテナはexitedで、十分な空きVRAMを確認してから既存コンテナのみ起動しました。
起動後は11474 MiB、検索中は11479 MiB、回答中と終了直前は11505 MiBでした。
停止後のsnapshotも区別して示します。連続測定したpeakではありません。

| GPU表示時刻（JST） | 状態 | 使用MiB | 空きMiB | GPU % |
| --- | --- | --- | --- | --- |
| 2026/10/09 21:57:22.584 | 検索中 | 11479 | 4583 | 33 |
| 2026/10/09 21:57:36.412 | 検索直後 | 11502 | 4560 | 4 |
| 2026/10/09 21:58:23.461 | 回答中 | 11505 | 4557 | 2 |
| 2026/10/09 22:01:35.845 | 停止後 | 2997 | 13065 | 5 |

| 用途 | alias / GGUF | SHA-256 | loopback port |
| --- | --- | --- | --- |
| embedding | nomic-embed-text / nomic-embed-text-v1.5.f16 | `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6` | 18082 |
| 回答 | gemma4-12b / Gemma 4 12B Q4_K_M | `1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606` | 18081 |

GGUFは今回も既存ファイルからSHA-256を計算し、前回と一致しました。
両imageのRepoDigestは `ghcr.io/ggml-org/llama.cpp@sha256:69019445c94c970496c8f6d6447214b837508162dfe1152768942c51237e3ab7`。
両コンテナの `llama-server --version` は0.5.0-dev、build 11347、commit 5fc4f3c8c、
GNU 14.2.0 / Linux x86_64です。固定revisionは `5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd`。
両healthはok、`/v1/models` のaliasは上記と一致しました。

| サーバー | 既存の主要設定（変更なし） |
| --- | --- |
| embedding | container内8080、embeddings、pooling=mean、ctx/batch/ubatch=2048、parallel=1、gpu-layers=99、threads=8、no-webui |
| 回答 | container内8080、ctx=4096、parallel=1、gpu-layers=99、fit=off、KV=f16/f16、flash-attn=on、threads/threads-batch=8、cache-ram=0、no-warmup、reasoning=off、enable_thinking=false、no-webui、no-agent、CORS=http://127.0.0.1:18081 |

公開bindは127.0.0.1のみ、GGUFはread-only mountです。
新モデルDL・image取得は行いませんでした。他のサービス（Ollama・Whisper・Irodori・LiveKit）を
停止・変更・起動していません。コンテナ・image・GGUFは削除していません。

profileはリポジトリ外の0700ディレクトリ、各0600ファイルに作成しました。
前回と同じ値: embedding enabled=true、alias/digestは上記、768次元、loopback `/v1`、timeout=15秒、
profile_id=nomic-v15-f16-115。回答はenabled=true / embedding.enabled=true /
chat.external_send_allowed=true、model=openai/gemma4-12b、transport=llamacpp_chat、
loopback `/v1`、timeout=60秒、profile_id=gemma4-12b-1278394b-115。
温度・seed・生成上限を追加せず、固定providerとサーバー既定を使用しました。
chat profileにmodel_digestはないため回答GGUFのSHA-256を本証跡へ別記しました。

## 固定データと実行

input schema=1、gold schema=2、合成62ケース・26分類、classifier=synthetic。
検索設定: candidate_pool_size=20、max_retrieved_memories=5、relevance_threshold=0.54、equivalence_margin=0.002。

| 固定ファイル | SHA-256 |
| --- | --- |
| `evals/semantic/cases.json` | `9f703b32ed79ac997320409dd38142324095084ec93164c60ea6b5aca9e50122` |
| `evals/semantic/expectations.json` | `0e979d561be09a45faf019baba285c14605f46ebacc6194f86b5298aa981caa4` |
| `evals/semantic/evaluation.card.json` | `17093470ae0139424d127bfc3308057b9bcface15dd70d0cf8bc45728c4bf3fa` |
| `evals/semantic/characters.json` | `0cfdd7aec0e6a69ecf601ab0ab16ad3696e53b987cf022a43c73ca09d533726f` |

```sh
T=/home/asa/dev/digital-souls-evidence/history-stage1-tools
export PATH=$T/bin:$T/node/bin:$PATH
export TMPDIR=/dev/shm
bash tools/evaluate-semantic-retrieval.sh --runs 3 \
  --profile <private-embedding-profile> --output <private-retrieval-report>
bash tools/evaluate-semantic-answer.sh --mode local_model --execute-local-model --runs 3 \
  --profile <private-answer-profile> --output <private-answer-report>
```

実際にはgit管理外の絶対pathを指定しました。検索3回と回答3回は別コマンドで直列実行し、
検索の完了を確認してから回答を開始しました。各コマンドのtimeoutは1700秒、実際の所要時間は下記です。
バックグラウンドの長時間実行や再試行はありません。
検索はvector cacheなし、回答はpromptfoo --no-cacheとcached=false検証です。
本番contextから回答を生成し、goldはモデルに渡していません。

| 評価 | 開始UTC | 終了UTC | 秒 | wrapper終了値 |
| --- | --- | --- | --- | --- |
| retrieval | 2026-10-09T12:56:55.307262+00:00 | 2026-10-09T12:57:32.628566+00:00 | 37.32 | 1（FAIL） |
| answer | 2026-10-09T12:57:44.838006+00:00 | 2026-10-09T13:00:33.188059+00:00 | 168.35 | 1（FAIL） |

回答promptfooの各プロセスはexit 100（決定論的assertion FAIL）、signalなし、raw_present=true、attempts=1。
report gateの独立再採点まで完了し、provider/実行error・欠落ケース・欠落runはありません。
stdout/stderrは固定診断分類のみreportに残し、生ログ・raw export・内部DBはrunnerが削除しました。

## 各回の全体結果

品質条件はquality_passed、全条件はcase.passedです。全体率は参考値で、合否は分類別90%と全必須ゲートです。

| 評価 | 回 | 完走 | 品質条件 | 全条件 | 必須ゲート違反ケース | 合否 |
| --- | --- | --- | --- | --- | --- | --- |
| 検索 | 1 | 62/62 | 41/62（66.13%） | 41/62（66.13%） | 21 | FAIL |
| 検索 | 2 | 62/62 | 41/62（66.13%） | 41/62（66.13%） | 21 | FAIL |
| 検索 | 3 | 62/62 | 41/62（66.13%） | 41/62（66.13%） | 21 | FAIL |
| 回答 | 1 | 62/62 | 52/62（83.87%） | 41/62（66.13%） | 21 | FAIL |
| 回答 | 2 | 62/62 | 52/62（83.87%） | 41/62（66.13%） | 21 | FAIL |
| 回答 | 3 | 62/62 | 52/62（83.87%） | 41/62（66.13%） | 21 | FAIL |

検索のembedding呼出しは183（各回61件、epoch_changeは候補0件で呼出しなし）。
quality_evidence=trueは実モデルによる測定であり、品質合格の意味ではありません。

## 分類別品質条件

各回のquality_passed/totalです。必須ゲート違反は別表であり、品質100%でも全体FAILの場合があります。

| 分類 | 検索1 | 検索2 | 検索3 | 回答1 | 回答2 | 回答3 |
| --- | --- | --- | --- | --- | --- | --- |
| synonym | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| paraphrase | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 | 10/10 |
| cross_language | 0/10 | 0/10 | 0/10 | 0/10 | 0/10 | 0/10 |
| unrelated | 0/10 | 0/10 | 0/10 | 10/10 | 10/10 | 10/10 |
| negation | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| update | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| multisource | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| multisource_revocation | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| private | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| excluded | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| deleted_source | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| deleted_memory | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| binding_character | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| binding_subject | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| binding_client | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| long_text | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| after_search | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| after_answer | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| epoch_change | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| fact_attachment | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| fact_version | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| fact_revocation | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| semantic_direct | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| semantic_derived | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| equivalent_order | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 | 1/1 |
| threshold | 0/1 | 0/1 | 0/1 | 1/1 | 1/1 | 1/1 |

検索はcross_language / unrelated / threshold、回答はcross_languageが各回90%未達です。
回答のunrelated / thresholdはgroundedではないため品質条件は真でも、no_memoryゲートでFAILです。

## 必須ゲート

違反件数。1ケースの複数違反は重複計上します。検索local_modelにexpected_orderゲートはありません。

| 評価 / ゲート | 回1 | 回2 | 回3 |
| --- | --- | --- | --- |
| 検索 / forbidden_ids | 0 | 0 | 0 |
| 検索 / threshold | 0 | 0 | 0 |
| 検索 / verified_records | 0 | 0 | 0 |
| 検索 / top_one | 10 | 10 | 10 |
| 検索 / dispatch | 0 | 0 | 0 |
| 検索 / context | 0 | 0 | 0 |
| 検索 / no_match | 11 | 11 | 11 |
| 回答 / forbidden | 0 | 0 | 0 |
| 回答 / dispatch | 10 | 10 | 10 |
| 回答 / lifecycle | 0 | 0 | 0 |
| 回答 / no_memory | 11 | 11 | 11 |

検索top_one違反と回答dispatch違反は日英10件です。該当なしの検索no_match / 回答no_memoryは11件です。
閾値未満混入0と、該当なしの実vectorが閾値以上になることを区別します。
禁止ID・禁止事実・正本検証・dispatch有効性・lifecycleに起因する違反は0件です。
dispatch FAILを一律にprivacy違反や無効context送信と同一視しません。

## 失敗ケース

以下は各3回で同じ品質/ゲート判定です。本文・query・回答全文は含めません。

| case ID | 分類 | 検索の失敗条件（全3回） | 回答の失敗条件（全3回） |
| --- | --- | --- | --- |
| cross-language-herb | cross_language | 品質, top_one | 品質, dispatch |
| unrelated-observatory | unrelated | 品質, no_match | no_memory |
| cross-language-02 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-03 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-04 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-05 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-06 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-07 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-08 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-09 | cross_language | 品質, top_one | 品質, dispatch |
| cross-language-10 | cross_language | 品質, top_one | 品質, dispatch |
| unrelated-02 | unrelated | 品質, no_match | no_memory |
| unrelated-03 | unrelated | 品質, no_match | no_memory |
| unrelated-04 | unrelated | 品質, no_match | no_memory |
| unrelated-05 | unrelated | 品質, no_match | no_memory |
| unrelated-06 | unrelated | 品質, no_match | no_memory |
| unrelated-07 | unrelated | 品質, no_match | no_memory |
| unrelated-08 | unrelated | 品質, no_match | no_memory |
| unrelated-09 | unrelated | 品質, no_match | no_memory |
| unrelated-10 | unrelated | 品質, no_match | no_memory |
| below-threshold | threshold | 品質, no_match | no_memory |

## 前回との差

前回は検索40/62・回答17/62が全条件合格でした。今回の全条件合格は検索41/62・回答41/62です。
検索品質41/62・回答品質52/62は前回から変わっていません。
検索の返却ID列・回答の送信ID列・品質判定は、前回reportとの比較で全ケース各回一致しました。
合否件数の差はモデルや設定の改善ではなく、順序完全一致から上位5件包含への基準変更によるものです。
検索のequivalent-band-orderは全順序不一致だけによるFAILが解消しました。
回答dispatch違反は45件から10件へ減り、残る10件はtop-1欠落です。
該当なしの回答11件はID照合を省いても空context要件でFAILです。
検索/回答とも日英分類未達等が残り、**品質は未受入**です。

## コンテナ停止と公開report確認

回答コマンドのfinallyで、品質FAIL時もdocker stopを両コンテナへ実行しました。
docker inspectで以下のexitedを確認し、後続の独立inspectでも再確認しました。

```text
/digital-souls-core-llamacpp-embed exited 2026-10-09T13:00:33.50007253Z
/digital-souls-core-llamacpp exited 2026-10-09T13:00:33.478414323Z
```

検索reportはEvaluationReport / validate_reportの再採点、回答reportはraw検査・Python再採点・
metadata照合を通過しました。公開前に全キー・文字列値を検査し、query・normalized_text・content・
answer・output・vector・資格情報・私有pathがなく、入力本文とfixture回答全文も含まれないことを確認しました。
公開reportのID・score・boolean・固定診断分類は観測値であり、モデルの入力にgoldを混ぜていません。

| 公開report | SHA-256 |
| --- | --- |
| [2026-10-09-semantic-real-model-retrieval-top5.json](2026-10-09-semantic-real-model-retrieval-top5.json) | `b19a9cf7bec6d6630b8b11d518cac7a6eb2df3a2d9e142d7814d16aca3ebaf97` |
| [2026-10-09-semantic-real-model-answer-top5.json](2026-10-09-semantic-real-model-answer-top5.json) | `46d9642dd9ecffde4f302da6a0a3e6b0a64f847452110575af82f210c31e0137` |

## 実装と品質ゲート

TDDの判定変更UTは実装前に70 FAIL / 176 PASS（RED）、実装後はPASSです。
最初のUT実行は試験側の未定義DATAによりcollection errorとなり、試験を修正してからREDを確認しました。
UT追加76件は全62ケースのtop-1導出62件、回答境界7件、検索mode/report/no_match/relevant全包含7件です。
Node追加1件はreport gateによる包含再採点・top-1欠落・偽造metadata拒否です。
IT1 / PostgreSQLの件数は増減なしです。

| コマンド | 結果 |
| --- | --- |
| uv sync --locked | PASS |
| uv lock --check | PASS |
| uv run --no-sync ruff check src tests tools/evaluate-semantic-retrieval.py evals/semantic/provider.py | PASS |
| uv run --no-sync ruff format --check src tests tools/evaluate-semantic-retrieval.py evals/semantic/provider.py | PASS、112 files |
| uv run --no-sync mypy | PASS、112 source files |
| uv run --no-sync pytest -m ut -q | PASS、684件（起点608、+76） |
| uv run --no-sync pytest -m it1 -q | PASS、590件（増減0） |
| uv build --no-build-isolation | PASS、sdist / wheel |
| bash tools/test-postgres.sh | PASS、410件（増減0、72.29秒） |
| (cd evals/semantic && npm ci --no-audit --no-fund) | PASS、575 packages |
| node --test --test-reporter=./tools/required-tests-reporter.mjs tools/*.test.mjs | PASS、59件（起点58、+1） |
| node tools/check-docs.mjs | PASS（証跡・reportをstage後も確認） |
| git diff --check / git diff --cached --check | PASS |
| bash tools/evaluate-semantic-retrieval.sh --runs 3 | PASS、62×3、fixture |
| bash tools/evaluate-semantic-answer.sh --runs 3 | PASS、62×3、fixture |

Node先行実行はnpm ci前の未取得better-sqlite3により2件FAILでした。
npm ci後の全59件はPASSです。最終品質ゲートのskip / xfail / xpass / TODO / cancelledは0です。
既存Starlette/Pydantic警告とnpm deprecated警告は残ります。GitHub CIはpush禁止のため **NOT RUN**。
各品質コマンドは30分以内に完了しました。

## 文書同期と制約

ADR 0023は本文/Statusを保持し日付付き置換注記のみ追加しました。
SPEC §3.2、評価README、評価ガイドは新ゲート定義を同期しました。
README / SPEC / docs/memory.md / PostgreSQL連携文書の実モデル状態は新証跡へ更新し、
検索/回答ともFAIL・品質未受入を維持しました。旧証跡/reportは残し、旧証跡末尾に再評価参照を追加しました。

- 実モデル品質は **FAIL**。分類器はsyntheticで、分類器の実モデル品質は **NOT RUN**。
- backend_identity_verified=false。GGUF照合・health/aliasは接続backend真正性の独立検証ではありません。
- 回答はNFKC→casefoldの部分文字列AND of ORsで、複合語・否定・時間関係を完全には判定しません。
- LLM judge、出典表記、回答言語の採点はありません。生回答を保持せず、語句の具体的な出力差は比較していません。
- 合成直接登録の測定です。形成・保存判定・再生成・TOUCH、実運用DB版6適用、形成〜利用の実環境IT2/STは **NOT RUN**。
- 私的corpus・人格品質・prompt injection耐性・性能/資源上限は受入対象外です。
- ハーネスの明らかな不具合は確認していません。期待値・閾値・serverを結果に合わせて調整していません。
- 監督のレビューが残ります。push / PR / mergeは **NOT RUN**（依頼で禁止）。
