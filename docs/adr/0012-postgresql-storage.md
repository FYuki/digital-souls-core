# ADR 0012: 明示選択するPostgreSQL履歴・記憶backend

Status: Proposed

一部を[ADR 0021](0021-postgresql-only-storage.md)のPostgreSQL一本化で置き換えます（SQLite実装を選択肢として維持する方針、`StorageConfig.backend`の選択肢。接続・保存・privacy・撤回の契約は維持）。

日付: 2026-10-05

## 背景

[ADR 0004](0004-conversation-history.md)と[ADR 0007](0007-memory-provenance-and-revocation.md)は、
履歴と記憶を同じSQLiteのtransactionで扱い、private化・履歴削除時に派生本文を即時撤回します。
このsliceでは既存のportと操作契約を保ち、PostgreSQLを明示選択できる保存adapterを追加します。
対象は空の専用schemaの初期化とbackend切替です。移送対象の実データはなく、既存SQLiteの移行や
正本履歴の自動抽出、稼働dogfoodへの適用は行いません。

## 選択肢と決定

SQLite実装を既存の選択肢として維持し、`PostgresHistory`・`PostgresMemory`をそれぞれ
HistoryStore・MemoryStore portのadapterとして追加します。SQL方言の違いはadapter内へ閉じ込め、
application/domainへpsycopgや接続設定を持ち込みません。

固定依存は`psycopg[binary]==3.3.6`です。PostgreSQL 18の公式imageを使う独立した合成試験を
検証対象とし、未検証の旧versionや外部managed serviceへの互換性を主張しません。
pgvectorは導入しません。意味検索の一時vectorは別の開発範囲であり、保存先を替える理由で
vectorの永続化や検索方式を追加しません。

`storage.py`の`StorageConfig`はstrictな`backend`（`sqlite` / `postgresql`）と対応する設定を持ち、
`open_storage(config)`が`StorageStores(history, memory)`を返します。両portを同じbackendに揃え、
履歴の撤回と派生記憶本文の消去を同じDBで確定できるようにします。
設定の読込みだけでは保存を有効にせず、trusted起動側でfactoryを呼び、storeとpolicyを明示注入します。
通常の`create_app()`とstateless経路は引き続き保存しません。接続失敗時のSQLite自動fallbackも行いません。

## 接続とschema

`PostgresConfig`はloopbackの`127.0.0.1`、または正規化された絶対POSIX Unix socketディレクトリを
要求します。hostname、remote host、URI、複数hostの指定を受け付けません。database・user・portを
明示し、専用schema名を使います。`public`、`information_schema`、`pg_`で始まるschemaは拒否します。

資格情報はtrusted起動設定の`SecretStr`で扱い、サンプルには含めません。暗黙のlibpq設定を避けるため、
非空の`PG*`環境変数は接続前に拒否し、passfileを`/dev/null/no-passfile`へ固定します。password未指定は空値を明示し、
環境やホームの設定から補完しません。接続先はローカルに限り、SSL・GSS暗号化・channel bindingは
無効です。認証方式も `none,password,md5,scram-sha-256` に固定し、暗黙の GSS/SSPI/OAuth 認証を使いません。
remote接続や認証/TLSの運用をこの契約へ広げません。

`PostgresDatabase.initialize()`はschema単位のtransaction advisory lockを取得します。
schemaが存在しなければ作り、空schemaへ全DDLとversion 1を同一transactionで登録します。
既存Core schemaはtable集合・列名/型/null/default/identity・PK/FK/UNIQUE制約・versionを照合して再利用し、不一致・部分schemaは拒否します。
既存DBの内容を書き換えて現在のschemaへ合わせる処理や、自動修復・移行は追加しません。

## transactionと同時操作

操作ごとに接続を作り、成功時commit、失敗時rollback、終了時closeします。connection poolや常駐接続は
持ちません。READ COMMITTEDで、read/writeとも専用schemaとBindingに対応するtransaction advisory lockを
取得します。これにより、同じBindingのsource読取り・採用・撤回を直列化します。単一操作の範囲を超えて
分類器・抽出器のawait中にDB transactionを保持せず、await後は既存のsource/epoch guardで再確認します。

schema名は識別子としてquoteし、search_pathは専用schemaとpg_tempへ固定します。
接続・statement・lockのtimeoutを明示します。DB障害は内容を含まないstorageエラーで返し、成功や
保存済みreceiptへ偽装しません。Binding単位の排他は初期実装の簡潔さを優先しており、
高負荷・多利用者向けの同時実行性能を検証した設計ではありません。

## 維持する履歴・記憶契約

- subject/client/audience/characterを含むtrusted Bindingで、履歴・source・memory・job・通知を分離します。
- request ID・fingerprint・期待revisionによる再試行と競合の契約を維持し、削除済み会話を遅い保存で復活させません。
- 指定発話の記憶除外とprivate中に保存したturnの非適格性を維持します。assistant/toolをuser factへ採用しません。
- private化はmemory epochを進め、履歴を残して派生本文をNULL化します。履歴削除も本文消去・通知を同じtransactionで確定します。
- private解除で旧記憶を復活させず、archiveは一覧表示だけを変えます。複数sourceの撤回後は残る適格sourceから明示的に再構築します。
- Memory ID・本文・source refs/epochs、抽出provenance、tombstone、内容なしoutbox、冪等jobの意味を維持します。

DBの接続権限はprivacy許可ではありません。保存・検索・推論送信は既存のpolicyを各境界で適用し、
許可不明なら拒否します。Bindingによる分離はapplicationの契約であり、DB管理者からの秘匿、RLS、
公開multi-tenant認証を新たに保証するものではありません。

## 検証と範囲外

既存の通信なしUT/IT1とは別に`postgres` markerを用意し、PostgreSQL 18の使い捨てserverで
合成データだけを検証します。履歴・除外・private・削除・公開範囲・由来・競合・初期化失敗の契約を
確認し、実DB未接続をSKIPで成功扱いにしません。CIも独立したPostgreSQL検証として実行します。

SQLite移行ツール、移行dry-run、backup/restore、自動import、PostgreSQL管理運用、dogfood切替、
remote接続、実モデル/GPU評価は対象外です。削除は論理的な取得停止と派生本文の消去を保証する範囲で、
DBの旧tuple・WAL・backup・snapshot・物理媒体上の消去を保証しません。

作業範囲は[Issue #43](https://github.com/FYuki/digital-souls-core/issues/43)で追跡します。

設定・検証手順は[PostgreSQL backend](../postgresql.md)、操作の契約は[履歴API](../history-api.md)と
[記憶API](../memory.md)を参照してください。
