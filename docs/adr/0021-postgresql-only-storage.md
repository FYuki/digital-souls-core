# ADR 0021: SQLiteを廃止しPostgreSQLへ一本化する

Status: Accepted

SQLiteの撤去は Epic #79（[Issue #88](https://github.com/FYuki/digital-souls-core/issues/88)）で完了しました。以下の決定・影響は決定時点の履歴です。

日付: 2026-10-07

Accepted日: 2026-10-07

根拠: 2026-10-07のユーザー決定（[Issue #78の確定事項・確定要件](https://github.com/FYuki/digital-souls-core/issues/78)）。
SQLite全廃・PostgreSQL一本化、ローカルもDockerイメージ、データ移送なし、記憶の正本はPostgreSQLのみとし、
SQLiteの撤去は後続のEpicで行います。

## 背景

[ADR 0012](0012-postgresql-storage.md)は、SQLite実装を既存の選択肢として維持し、
PostgreSQLを明示選択できる履歴・記憶backendとして追加しました。
ユーザーは2026-10-07に、保存backendをPostgreSQLへ一本化し、SQLiteを全廃することを決定しました。
運用前のためSQLiteからのデータ移送は行わず、決定の記録と既存実装の撤去を分けます。

## 決定

- 履歴・記憶の保存先をPostgreSQLだけにします。ADR 0012の「SQLite実装を既存の選択肢として維持」と、
  `StorageConfig.backend`の選択肢（`sqlite` / `postgresql`）を維持する決定を置き換えます。
- 記憶の正本（Episode・Fact・Semantic、[Issue #72](https://github.com/FYuki/digital-souls-core/issues/72)）は
  PostgreSQLだけに実装し、SQLite版は作りません。
- ローカルPCでも、digest固定の公式PostgreSQLイメージをDockerで起動します。
  具体的な起動手順・compose等はSQLite撤去のEpicで整備します。
- 保存backendに依存する試験は、[CONTRIBUTING](../../CONTRIBUTING.md#postgresql-adapter-の合成契約テスト)の
  既存方針に従い、ネットワークなしの使い捨てコンテナ上の`postgres` markerの合成試験で行います。
  domain・保存に依存しない処理のUT/IT1はプロセス内のままとします。
- 運用前のため、SQLiteからPostgreSQLへのデータ移送は行いません。
- 既存SQLiteの撤去と、SQLiteを使う試験の移行は後続のEpicで行います。
  撤去までの間、既存のSQLite adapterは現状維持とし、新しい機能をSQLiteへ追加しません。

## 影響

- 本ADRは決定の記録であり、SQLite adapterや`StorageConfig.backend`の現行実装はまだ撤去・変更しません。
- ADR 0015の保存backendの読み替えとADR 0016の両adapterでの契約試験の前提にも、PostgreSQL一本化の決定を適用します。
- ADR 0012のうち、上記の保存backendの選択肢以外の接続・保存・privacy・撤回の契約は維持します。
- 新しい記憶の正本とその保存契約試験はPostgreSQLのみを対象とします。
  撤去手順と既存試験の移行手順はこのADRでは定めません。

## 参照

- [Issue #78](https://github.com/FYuki/digital-souls-core/issues/78)：ユーザー決定と本ADRの作業範囲
- [Issue #72](https://github.com/FYuki/digital-souls-core/issues/72)：Episode・Fact・Semanticの正本
- [ADR 0012](0012-postgresql-storage.md)：置き換える保存backendの選択肢
- [ADR 0015](0015-memory-model-reorganization.md)、[ADR 0016](0016-memory-kinds-and-records.md)：記憶モデルと正本
- [PostgreSQL backend](../postgresql.md)：現行の接続・検証境界
