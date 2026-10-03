# 製品の背景

このリポジトリでは、小さく、プロバイダーに依存しないCoreを検討します。
次の範囲は議論の出発点であり、承認済みAPIではありません。

- キャラクター定義と、対話に必要なコンテキスト。
- プライバシー判断と、保存・検索・外部送信のポリシー。
- 記憶の抽出・採用・訂正・削除。
- プロバイダーのadapterを交換できるLLM port。

音声・STT・TTS、LiveKit、常駐エージェント基盤、scheduler、worker、UIは
現在のCoreの対象外です。最初の実装は人格文脈付きLLM Providerの
[推論API](docs/api.md)です。外部Agentのtool実行ループを持たず、通常チャットUIからも呼べます。
明示的な記憶抽出・参照検索の最小実装は[記憶API](docs/memory.md)に記載しています。自動技能学習は未実装です。明示的な会話履歴の保存・復元は
[ADR 0004](docs/adr/0004-conversation-history.md)、機微情報の検査と許可境界は
[ADR 0005](docs/adr/0005-privacy-boundaries.md)に記載しています。保存は既定拒否・明示注入のままです。
分類器の実モデル精度は未評価で、私的実会話を自動取り込みしません。

開発規約はこの文書に重複させず、[CONTRIBUTING](CONTRIBUTING.md)で管理します。
