# Digital Souls Core

プロバイダーに依存しない最小限のCoreを検討するための公開リポジトリです。

開発・検証は[CONTRIBUTING](CONTRIBUTING.md)、暫定的な製品の範囲は
[CONTEXT](CONTEXT.md)を参照してください。エージェント向けの入口は
[AGENTS](AGENTS.md)です。決定は[ADR](docs/adr/README.md)、進捗は
[Issue](https://github.com/FYuki/digital-souls-core/issues)、検証結果は
[日付付き証跡](docs/evidence/2026-10-02-bootstrap.md)で管理します。

最初の[キャラクター推論API](docs/api.md)をPython/FastAPI/LiteLLMで実装しています。
通常チャットと外部Agentのtool call往復に対応する小範囲のChat Completions APIです。
localhostの単独利用者向けで、公開サービス用の認証・記憶永続化・tool実行は未実装です。
サンプルは外部送信を拒否し、fakeで無課金検証できます。

ローカルGemma 4を使う場合は[llama.cppの起動・切替・rollback](docs/llamacpp-operations.md)を参照してください。
固定Dockerと運用者profileを使用し、Ollamaや他クライアントの設定を自動変更しません。

[光織 / Miori](characters/miori/README.md)をサンプルキャラクターとして格納しています。
素材固有の利用条件と、保留・省略した項目のmanifestを確認してください。
