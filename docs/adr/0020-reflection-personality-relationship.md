# ADR 0020: 内省・人格・関係・生活状態と記憶の接続

Status: Proposed

日付: 2026-10-06

## 背景

Coreは人格の文脈付き推論を提供しますが（[ADR 0001](0001-character-inference-api.md)）、経験から人格・関心・
関係が変化する仕組みは持ちません。[ADR 0015](0015-memory-model-reorganization.md)に従い、PoCの
[Character Life共通契約](https://github.com/FYuki/digital-souls/blob/fce7382884d981c42be7fbd3ddaffe7469e27588/docs/decisions/character-life-memory-personality-autonomy-2026-09.md)
の記憶・人格に関する部分を採用します。会話外の自律活動の実行（第8〜11節）は、Core外の実行基盤との
境界として扱います。

## 決定

### 1. 全体の流れ

```text
保存済み会話 / 許可された活動
  +-> Episode / Fact形成
  |      +-> 一般化 -> EXPERIENCE_DERIVED Semantic
  |      +-> Reflection
  |             +-> Current Interests / Intention（Life State）
  |             +-> Personality Adaptation -> Personality
  +-> 直接抽出 -> DIRECT_EXTRACTION Semantic
```

Memory、Fact、Reflection、Personality、Relationship、Skill、runtime stateを同じ正本として扱いません。
人格そのものを記憶の一種として扱いません。

### 2. Reflection

- 本人が複数の経験をどう認知・評価し、何を感じ、何を大切にし、今後どうしたいと捉えたか。
  Semanticとは別の永続正本とする。
- 状態はACTIVE / SUPERSEDED / INACTIVE。同じ論点の捉え方が変わったら旧版をSUPERSEDEDとして残す。
  異なる観点は共存できる。
- 新しい関連経験や根拠の訂正・削除で再評価する。Personalityの変更だけでは再内省しない。
- 旧Reflectionは補助情報であり、独立したEpisode根拠に数えない。
- 通常会話の検索・promptへ直接注入しない。
- Reflectionから、Insight（自己洞察）、Current Interests、Goal Intention、Implementation Intentionを
  別の検証済み結果として派生できる。

一般化・Reflectionの形成は独立した2件以上の経験を最低条件とし、同じ話題の出来事を二重に数えません。
privacyは派生元が保存可能でも再評価します（複数の安全な経験から機微情報を推論し得るため）。

### 3. Life State

会話終了後も中期的に続く状態として、Interest、Ongoing Activity、Goal Intention、Implementation Intention、
Next Action Candidate、Share Candidateを持ちます。Interestだけでは外部活動を開始しません。
IntentionはACTIVE / COMPLETED / ABANDONED / SUPERSEDEDのlifecycleを持ちます。減衰等の具体値は運用で調整します。

### 4. Temperament と Personality

- **Temperament（気質・不変）**：経験で変更しない核となる性質・価値観・制約。変動人格より上位の制約。
- **Personality（人格・可変）**：正本はBig Five Aspectsの10因子（Volatility、Withdrawal、Compassion、
  Politeness、Industriousness、Orderliness、Enthusiasm、Assertiveness、Openness、Intellect）、値は[-1.0, +1.0]。
  数値をそのままLLMへ渡さず、自然言語の人格文脈へ変換する。
- Egogramは表出の一貫性を質的に評価する評価機であり、人格の正本や更新の入力にしない。

人格の更新（Personality Delta）は次を守ります。

- LLMに数値のdeltaを自由に決めさせない。主な入力はACTIVEなReflectionとその根拠の独立Episode。
- 同じEpisodeを同じ特性へ複数回加算しない（episode × trait単位で最新の有効なReflectionだけを採用）。
- 根拠の重みは経験日時を基準とした指数減衰`w = 2^(-(t - experienced_at) / half_life)`を基本とし、
  支持・反証を同じ方式で集計して閾値を超えた場合だけ上限付きのdelta候補を作る。
- 単一Episodeだけで強い人格変更を確定しない。相反するReflectionを無視しない。
- `half_life`、`min_support`、`update_threshold`、`max_delta_per_update`、`cooldown`は設定値とし、
  上限・頻度・許可特性をapplicationが検証する。変更履歴・由来・rollbackを保持する。

### 5. Relationship と Interpersonal Skill

Relationship Stateは人格と分離し、相手ごとに`affective_valence`と`relational_proximity`（各[-1.0, +1.0]）を
持ちます。「距離を詰めるのがうまい」等はInterpersonal Skillとして手続き記憶の学習に含め、Relationshipを
直接書き換えません。実際の対話 → Episode / Reflection を経て影響します。

### 6. 会話外の活動との境界

Coreには外部Agentのtool実行ループを持たない方針があります（ADR 0001）。PoCの自律活動の契約
（Autonomy Target、外部送信直前のEgress Privacy Check、Minimum Disclosure、High Impact操作の確認、
実行結果の状態）は、会話外の活動を実行する基盤に適用する契約として参照します。Coreがどこまで所有するかは
[SPEC](../../SPEC.md)の要決定事項です。いずれの場合も、活動からの経験は本ADR群の形成・privacy・失効の
契約を通して記憶へ入れます。

### 7. 優先順位と実行基盤

処理の優先順位は「前景の会話 > ユーザーが依頼した活動 > 自律的な背景処理」とします。前景の会話開始時に
背景処理を強制停止するかは、実測してから決めます。orchestration・queue・scheduling・待機と再開・
checkpointは外部の実行基盤へ委譲でき、正本の更新条件・privacy・lineage・人格delta上限・活動の権限境界は
Coreの共通契約として維持します。

## 影響

- Reflection、Life State、Personality、Relationshipの正本と更新処理は、記憶の形成基盤
  （[ADR 0016](0016-memory-kinds-and-records.md)、[ADR 0017](0017-memory-formation-admission.md)）の後に実装します。
- 根拠の失効時は[ADR 0019](0019-memory-correction-invalidation.md)に従い、影響する特性と残る根拠から再評価します。

## 参照

- PoC参照revision: `fce7382884d981c42be7fbd3ddaffe7469e27588`
