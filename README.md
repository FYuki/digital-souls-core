# Digital Souls Core

プロバイダーに依存しない最小限のCoreを検討するための公開リポジトリです。

開発・検証は[CONTRIBUTING](CONTRIBUTING.md)、暫定的な製品の範囲は
[CONTEXT](CONTEXT.md)を参照してください。エージェント向けの入口は
[AGENTS](AGENTS.md)です。決定は[ADR](docs/adr/README.md)、進捗は
[Issue](https://github.com/FYuki/digital-souls-core/issues)、検証結果は
[日付付き証跡](docs/evidence/2026-10-02-bootstrap.md)で管理します。

最初の[キャラクター推論API](docs/api.md)をPython/FastAPI/LiteLLMで実装しています。
通常チャットと外部Agentのtool call往復に対応する小範囲のChat Completions APIです。
localhostの単独利用者向けで、公開サービス用の認証・tool実行は未実装です。
記憶永続化は明示的なopt-inで利用でき、既定では接続しません。
サンプルは外部送信を拒否し、fakeで無課金検証できます。

ローカルGemma 4を使う場合は[llama.cppの起動・切替・rollback](docs/llamacpp-operations.md)を参照してください。
固定Dockerと運用者profileを使用し、Ollamaや他クライアントの設定を自動変更しません。

[光織 / Miori](characters/miori/README.md)をサンプルキャラクターとして格納しています。
素材固有の利用条件と、保留・省略した項目のmanifestを確認してください。

## 明示的な会話履歴（第1段階）

既存APIはstatelessのままです。保存・復元・一覧・削除の専用経路と、既定拒否の保存policy境界を
[会話履歴API](docs/history-api.md)に記載しています。ローカル分類器と明示的な記憶抽出・参照検索は実装済みです。
明示注入の意味検索とローカル embedding adapter も実装済みです。
実モデルの分類・抽出・検索品質は未検証です。

機微情報の明示的な検査・保存と送信の許可境界は[privacyガイド](docs/privacy.md)を参照してください。

Stage3の明示的な記憶抽出・保存・参照検索と未検証範囲は[記憶API](docs/memory.md)を参照してください。

保存先を明示選択する [PostgreSQL backend](docs/postgresql.md) は、空の専用 schema を初期化し、
履歴・記憶の既存契約を保ちます。通常のアプリは保存無効のままで、SQLite からのデータ移送は行いません。

PostgreSQL と意味検索を同時に使う trusted 起動側の構成・未実施の配備作業は
[統合と配備の境界](docs/semantic-postgresql-integration.md)を参照してください。
