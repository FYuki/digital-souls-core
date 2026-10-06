# 製品の背景と用語

## 製品の背景

このリポジトリでは、小さく、プロバイダーに依存しないCoreを開発します。Coreは、キャラクターとの
継続的な会話・記憶・人格を一つの境界で扱い、複数の入口（チャットUI、外部Agent等）から同じ人格を
利用できるようにします。

Coreの範囲は次のとおりです。

- キャラクター定義と、対話に必要なコンテキスト。
- プライバシー判断と、保存・検索・外部送信のポリシー。
- 会話履歴と、記憶の形成・訂正・削除・検索。
- 経験からの内省・人格・関係の更新（[ADR 0020](docs/adr/0020-reflection-personality-relationship.md)）。
- プロバイダーのadapterを交換できるLLM port。

音声・STT・TTS、LiveKit、UIはCoreの対象外です。Coreは外部Agentのtool実行ループを持たず、
通常チャットUIからも呼べます（[推論API](docs/api.md)）。記憶の形成jobの起動や会話外の活動を
実行する基盤との分担は、[SPEC](SPEC.md)の要決定事項です。

記憶モデルはPoC（公開`FYuki/digital-souls`）で採用済みの決定を移設したものです
（[ADR 0015](docs/adr/0015-memory-model-reorganization.md)）。機能の実装状況と受入条件は[SPEC](SPEC.md)、
現行の記憶APIは[記憶API](docs/memory.md)、開発規約は[CONTRIBUTING](CONTRIBUTING.md)で管理します。
保存は既定拒否・明示注入のままで、私的な実会話を自動で取り込みません。
分類・抽出・検索の実モデル品質は未評価です。

## 用語

このリポジトリでの意味を記します。正式な判断はADR、現在の挙動はコード、進捗はIssueが正本です。
「状態」は[SPEC](SPEC.md)と同じ基準（2026-10-06のmain）です。

### 境界と会話

| 用語 | 意味・区別 | 状態・参照 |
| --- | --- | --- |
| Binding | subject・client・audience・characterの組。履歴・記憶・人格の所有境界で、別Bindingの情報を混ぜない | 実装済み：[ADR 0004](docs/adr/0004-conversation-history.md) |
| Conversation / 会話、スレッド | 保存する会話のまとまり。作成・再開・アーカイブ・削除の単位。スレッドは記憶の増分抽出の枠でもあるが、知識の参照・訂正はBinding全体に及ぶ | 実装済み：[履歴API](docs/history-api.md) |
| Source / 出典、source epoch | 記憶の根拠となる元発言（会話・turn revision・message index）と、private化等で進む撤回世代 | 実装済み：[ADR 0007](docs/adr/0007-memory-provenance-and-revocation.md) |
| 指定発話の記憶除外、プライベートモード、アーカイブ | 履歴は残して記憶の対象から外す操作、スレッド単位で記憶の対象外にする操作、一覧から隠すだけの操作 | 実装済み：[ADR 0006](docs/adr/0006-conversation-memory-controls.md) |
| privacy permission | history・local・external・memoryの別許可。Binding単位でoperatorが明示する | 実装済み：[ADR 0005](docs/adr/0005-privacy-boundaries.md) |

### 記憶

| 用語 | 意味・区別 | 状態・参照 |
| --- | --- | --- |
| Working Memory / 作業記憶 | 現在の入力・目的・処理中の文脈。長期保存しない | 概念：[ADR 0016](docs/adr/0016-memory-kinds-and-records.md) |
| Conversation History / 会話履歴 | 同じ会話を継続するための履歴。別の会話から検索しない。長期記憶とは別 | 実装済み：ADR 0004 |
| Long-term Memory / 長期記憶 | 会話を越えて参照する記憶の総称。Episodic・Semantic・Reflective・Proceduralを含む | 一部：ADR 0016 |
| Episode / エピソード記憶 | 所有キャラクターが何を経験したか。経験の5W（必須はWhatの述語のみ）と経験日時を持つ。「話を聞いた」も経験 | 未実装：ADR 0016 |
| Fact / 関連事実 | 経験で得た、話題の対象についての情報・申告内容。独立したIDを持ち、Episodeから参照する。検証済みの真実やSemanticの正本ではない | 未実装：ADR 0016 |
| Fact Merge / Fact Update | 別々のFactを同じ出来事として版付きのIDで結ぶ処理／対象が明確な補足・訂正でFactの内容版を更新する処理 | 未実装：[ADR 0017](docs/adr/0017-memory-formation-admission.md) |
| Semantic Memory / 意味記憶 | 知識として採用した事実・概念・傾向。形成方法は明示命題の直接抽出（DIRECT_EXTRACTION）と経験からの一般化（EXPERIENCE_DERIVED） | 未実装：ADR 0016 |
| Reflective Memory / Reflection / 内省 | 本人が経験をどう意味づけたか。Semanticとは別の正本で、通常会話へ直接注入しない | 未実装：ADR 0020 |
| Procedural Memory / Skill / 手続き記憶 | どう実行するかの記憶。実行・対話の結果から学習し、実行時に参照する | 未実装：ADR 0016 |
| Candidate / 候補 | LLM等が生成し、privacy・根拠・schema・policyの検証前のデータ。検証を通ったものだけを自動で保存する | 概念：ADR 0016 |
| 保存判定（admission） | 候補をDENY_SENSITIVE・DENY_USER_REQUEST・ABSTAIN_UNKNOWN・NOT_MEMORY_WORTHY・ALLOW_STRUCTUREDに決定論的に分類する処理 | 未実装：ADR 0017 |
| stated_at / experienced_at / 対象日時 | 元発言の日時／キャラクターが経験を得た日時／話題の出来事の日時。互いに補完しない | 未実装：ADR 0016 |
| last_user_mentioned_at / TOUCH | ユーザーが最後に明示的に言及した日時／再言及時にこの日時だけを更新する処理。検索の同順位の並べ替えに使う | 未実装：[ADR 0018](docs/adr/0018-memory-retrieval-context.md) |
| 派生index | 正本から再構築できる検索用の索引。現行は呼出し中だけの一時vector | 一部：[ADR 0010](docs/adr/0010-in-process-memory-search.md) |
| Consolidation / 記憶整理 | 同種の既存記憶をKEEP・MERGE・SUPERSEDE等の型付き計画で整理する処理。一般化やFact統合とは別 | 未実装：ADR 0017 |
| Invalidation / 失効 | 根拠の訂正・削除・撤回で、依存する記憶・派生結果を即時に利用停止し、残る根拠から再評価する処理 | 一部：[ADR 0019](docs/adr/0019-memory-correction-invalidation.md) |
| Forgetting / 忘却 | 記憶内容の削除ではなく、想起しにくくなること。必要性が確認できた段階で詳細化する | 概念のみ |

### 人格と状態

| 用語 | 意味・区別 | 状態・参照 |
| --- | --- | --- |
| Temperament / 気質 | 経験で変わらない核となる性質・価値観・制約。人格より上位の制約 | 概念：ADR 0020 |
| Personality / 人格 | 経験と内省から緩やかに変わる持続的な傾向。正本はBig Five Aspectsの10因子 | 未実装：ADR 0020 |
| Life State / 生活状態 | Interest、Ongoing Activity、Goal / Implementation Intention等の中期的な状態 | 未実装：ADR 0020 |
| Current Interests / 現在の興味関心 | 今、注意や好奇心が向いている対象。Reflectionから派生し、会話の話題選択に使う | 未実装：ADR 0020 |
| Relationship State / 関係 | 相手ごとの感情の正負と接近・分離の2軸。人格とは別 | 未実装：ADR 0020 |
| Interpersonal Skill | 対人行動を上手く実行する能力。手続き記憶として学習し、関係を直接書き換えない | 未実装：ADR 0020 |
