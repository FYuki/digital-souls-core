# ADR 0024: 記憶検索の embedding を多言語モデル bge-m3 へ切り替える

Status: Proposed

日付: 2026-10-10

根拠: 2026-10-10 のユーザー決定（[Epic #124 の Q1〜Q5](https://github.com/FYuki/digital-souls-core/issues/124)）と、
[Issue #130 の候補比較](../evidence/2026-10-10-semantic-embedding-candidates.md)。

## 背景

[ADR 0023](0023-semantic-evaluation-contract.md)の62ケースによる実モデル評価で、nomic-embed-text-v1.5 f16（接頭辞なし）は
検索・回答とも FAIL でした。日英 0/10、無関係 0/10、閾値 0/1 です（[証跡](../evidence/2026-10-09-semantic-real-model-evaluation-top5.md)）。

Q1・Q2 に従い、nomic のタスク接頭辞の有無と多言語 embedding モデルを比べました。Q3 に従い、比較には
合否判定用の62ケースとは別の[調整用の合成89件](../../evals/semantic/tuning/README.md)を使い、62ケースでは候補を評価していません。
候補20・最大5・同等帯0.002・タイブレーク・合否基準は Q4 により変えていません。

閾値0.54での調整用ケースの結果（各候補3回、3回とも同じ）は次のとおりです。

| 候補 | synonym /10 | paraphrase /10 | cross_language /24 | unrelated /22 | threshold /12 |
| --- | --- | --- | --- | --- | --- |
| nomic v1.5 f16（接頭辞なし、現行） | 9 | 8 | 0 | 0 | 6 |
| nomic v1.5 f16（search_query / search_document） | 9 | 8 | 0 | 0 | 6 |
| nomic v2 MoE f16（search_query / search_document） | 5 | 9 | 0 | 18 | 9 |
| bge-m3 Q8_0（接頭辞なし、CLS） | 10 | 10 | 20 | 12 | 6 |
| multilingual-e5-large Q8_0（query / passage） | 10 | 10 | 24 | 0 | 6 |

閾値を0.40〜0.80で掃引しても、全分類90%と必須ゲート違反0を同時に満たす候補・閾値はありませんでした。

## 選択肢

1. **nomic v1.5 を維持し、接頭辞・閾値だけを変える。** 接頭辞を付けても日英は改善せず（0.54で0/24、最良でも21/24）、
   日英と無関係を同時に満たす閾値がありません。
2. **bge-m3 へ切り替え、閾値0.54を維持する（推奨）。** 同義語・言い換えは10/10、話題が遠い無関係は12/12、日英は20/24です。
   掃引の中で、主要分類の最低成績が最も高い点です。閾値を0.52にすると日英24/24、話題が遠い無関係8/12です。
3. **multilingual-e5-large へ切り替え、閾値を0.60〜0.61へ上げる。** 正解の取りこぼしはありませんが、
   無関係は0/22で、該当なしの質問に記憶を返します。
4. **nomic v2 MoE へ切り替える。** 無関係は18/22ですが、0.54で同義語5/10・日英0/24です。

## 決定（提案）

- 記憶検索の embedding モデルを **bge-m3**（BAAI、MIT）の GGUF Q8_0 にします。
  - ファイル：`ggml-org/bge-m3-Q8_0-GGUF` revision `9eba04c5d75ba5a1595e45de734d36bef4e5cb98` の `bge-m3-q8_0.gguf`、
    SHA-256 `aa473d51f451a22f0fcf39ba3330c14bed38a385712b1113440f69df4047a173`、634,553,760 bytes。
  - llama.cpp は既存と同じ固定イメージを使い、pooling は `cls`、次元は1024です。
  - 接頭辞は付けません（モデルカードの推奨どおり）。profile へ接頭辞の設定は追加しません。
- relevance 閾値は **0.54 を維持** します。候補20・最大5・同等帯0.002・タイブレーク（`last_user_mentioned_at DESC NULLS LAST → created_at DESC → id ASC`）・
  relevance の式 `1/(1+sqrt(二乗L2))` も変えません。ADR 0018・0022・0023 の検索設定の本文は変わらないため、置換注記は付けません。
- 0.54 は PoC の nomic 系の設定値でしたが、今後は bge-m3 の relevance 空間での値として扱います。モデルを変える場合は閾値も再調整します。
- 本番で embedding のベクトルは永続化していません（ADR 0011・0022）。モデルの切替でデータの移行は不要です。実装時にこの前提を確認します。

## 影響

- `compose.llamacpp.yml` と設定文書に、bge-m3 の embedding サーバーの起動設定（モデルの SHA-256 確認、pooling、loopback の port）を追加・更新します。
  現行の nomic 用 embedding コンテナは手動作成のため、切替の手順も文書にします。
- `LocalEmbeddingProfile` の model・digest・dimensions（1024）の設定例と評価用 profile を更新します。adapter のコードは変えません。
- VRAM は embedding サーバーの読込みで約0.6 GB 増えます（nomic v1.5 は約0.55 GB）。
- 62ケースの実モデル再評価は [Issue #132](https://github.com/FYuki/digital-souls-core/issues/132)で行います。結果は FAIL の可能性があります。
  - 調整用ケースの0.54では、日英は 20/24（83%）で90%に届いていません。
  - 同じ対象の別属性を問う「近い型」の無関係質問は、0.54で 0/10 です。どの候補・閾値でも、正解のある質問と relevance が重なりました。

## 残る課題（この ADR では扱わない）

- 近い型の無関係質問は、単一の embedding と閾値では分離できません。reranker や回答側の判定など別の手段が必要で、
  採否は後続で決めます。62ケースの unrelated は話題が遠い型なので、この課題は62ケースの合否には直接は現れません。
- 調整用ケース・NoMIRACL の先頭 passage・MKQA の先頭99ペアに過適合している可能性があります。
- F16 と Q8_0 の量子化の違いを分離していません。長い passage・多数の候補・同時リクエストでの VRAM と速度は未測定です。
