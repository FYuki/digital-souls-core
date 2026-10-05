# 明示選択するPostgreSQL backend

履歴・記憶の保存先をtrusted起動コードでSQLiteまたはPostgreSQLへ切り替えます。
PostgreSQLは空の専用schemaを初期化して使います。既存のSQLiteからデータを移す機能はありません。
通常の`create_app()`は保存無効のままで、設定ファイルを置いただけでは接続・保存・記憶抽出を始めません。
設計は[ADR 0012](adr/0012-postgresql-storage.md)を参照してください。

## 明示接続

[設定例](../examples/storage.postgresql.example.json)は秘密を含まない合成設定です。
database・user・portは例であり、稼働サービスに対応する確認済み値ではありません。
DBと利用roleは運用者が事前に用意します。CoreがDB・role・PostgreSQLサービスを作成することはありません。

```python
from pathlib import Path
from digital_souls_core.storage import StorageConfig, open_storage

config = StorageConfig.model_validate_json(
    Path("examples/storage.postgresql.example.json").read_text(encoding="utf-8")
)
# 明示した接続先へ接続し、空の専用schemaを初期化する。
stores = open_storage(config)

# inferenceと現在のpolicyはtrusted起動側で明示構成済み。
# create_app(inference, history_store=stores.history, history_policy=policy)
# MemoryService(stores.memory, policy, extractor)
```

`StorageConfig.backend`は必須です。`sqlite`では任意の`sqlite_path`、`postgresql`では`postgres`を
指定します。型の暗黙変換や未知field、backendと整合しない設定は拒否します。
SQLiteを選ぶ場合も、既存のGit外保存先・POSIX権限・symlink拒否等の条件を維持します。

`StorageStores`は同じbackendのhistory/memory portをまとめて返します。historyとmemoryを別DBへ
任意に分ける設定は提供しません。`open_storage`の明示呼出しにはDB初期化の副作用がありますが、
履歴経路へstore/policyを注入する操作と記憶抽出の明示呼出しは別です。履歴を保存しただけで
正本会話を意味記憶へ取り込まず、既存stateless APIにも自動保存を追加しません。

## PostgreSQL設定

`PostgresConfig`は`digital_souls_core.postgres_db`にあります。

| field | 条件・既定値 |
| --- | --- |
| `host` | `127.0.0.1`、または正規化された絶対POSIX Unix socketディレクトリ。既定は`127.0.0.1` |
| `port` | 1〜65535、既定5432 |
| `database` / `user` | 必須。1〜63文字の単純な名前 |
| `password` | 任意の`SecretStr`。未指定は空値を明示し、環境から補完しない |
| `schema_name` | 小文字の専用識別子、最大63文字。既定`digital_souls_core`。`public`等は拒否 |
| `connect_timeout` | 1〜30秒、既定5秒 |
| `statement_timeout_ms` | 1〜30000 ms、既定5000 ms |
| `lock_timeout_ms` | 1〜30000 ms、既定3000 ms |

hostname・remote host・接続URI・複数hostは受け付けません。libpqへの設定は明示引数に固定し、
非空の`PG*`環境変数がある場合は接続前に拒否します。passfileは`/dev/null/no-passfile`で、ホームの`.pgpass`も
使いません。設定名を`PG*`へ置いたまま暗黙に反映する運用は行いません。
ローカル限定の初期構成ではSSL・GSS暗号化・channel bindingを無効にしています。
認証方式も `none,password,md5,scram-sha-256` に限定し、暗黙の GSS/SSPI/OAuth 認証を使いません。

サンプルにはpasswordを含めず、実際の資格情報はtrusted起動側で管理します。HTTP callerから接続先・
schema・password・scopeを指定する機能はありません。DB接続権限だけでhistory/memory permissionを
許可することもありません。

## 初期化と復旧境界

`PostgresDatabase(config).initialize()`は専用schemaを初期化し、History/Memory adapterの構築時にも
同じ処理を使います。schema単位のtransaction advisory lockを取り、存在しなければschemaを作り、
空schemaへtableとversion 1を原子的に登録します。

既存Core schemaはtable集合・列名/型/null/default/identity・PK/FK/UNIQUE制約・versionを照合します。不一致や途中のschemaは拒否し、
旧schemaを自動修復・変換しません。この確認を、DBの全設定・権限・任意の改変の監査とは扱いません。
初期化途中の失敗ではtransactionをrollbackし、正常な空状態から再実行できる境界を持ちます。
初期化先に既存データを移送せず、SQLiteファイルを書き換えたり削除したりしません。

各storage操作は接続を作り、transactionでcommit/rollback後にcloseします。read/writeとも
Binding単位で直列化し、分類器や抽出器のawait中はtransactionを持ち越しません。
競合・再試行・source撤回は既存のrevision/epoch/receipt契約を使います。接続・timeout・SQL障害を
内容なしのstorageエラーとして返し、別backendへ自動切替しません。

## private・除外・削除・公開範囲

[会話操作](history-api.md)と[記憶操作](memory.md)の意味は保存先に依存させません。
指定発話は履歴へ残しながら記憶対象から除き、private thread由来のsourceを使いません。
private化と履歴削除は、派生memory本文のNULL化、epoch/通知の更新を同じtransactionで確定します。
consumer停止中も旧本文を検索できず、private解除や遅いcommitで旧記憶を復活させません。
archiveは一覧から隠すだけで、記憶sourceの条件を変えません。

Bindingのsubject/client/audience/characterを全操作で照合し、Memory/sourceのID・epoch・抽出provenanceを
保持します。複数sourceの撤回後は残る適格sourceから再構築し、旧本文を再構築入力にしません。
この分離はapplicationのport契約であり、DB管理者に対する秘匿やRLS・公開multi-tenant認証の実装ではありません。

削除は取得停止と派生本文の論理的消去です。PostgreSQLの旧tuple、WAL、backup、snapshot、物理媒体の
消去保証は追加しません。今回は実データがなく、backup/restore手順や移行dry-runも作成しません。

## 合成データによる独立検証

依存は`psycopg[binary]==3.3.6`をlockし、PostgreSQL 18公式imageの使い捨てserverを検証対象にします。
通常の`ut`・`it1`は外部通信を禁止したまま、実DB試験は独立した`postgres` markerで実行します。
LLM、API key、GPU、pgvectorは不要です。

再現するには、Docker と固定 uv を用意して `bash tools/test-postgres.sh` を実行します。
ネットワークなし・公開ポートなしの一時 DB と専用 socket を作り、終了時に削除します。

Unix socketを持つ使い捨てserver・専用DBを個別に用意したテスト環境では、次の4変数を明示します。
以下の値は合成例であり、既存の運用DBへ向けて実行しません。

```sh
DSC_TEST_POSTGRES_SOCKET=/tmp/dsc-postgres-test \
DSC_TEST_POSTGRES_PORT=5432 \
DSC_TEST_POSTGRES_DATABASE=core_synthetic \
DSC_TEST_POSTGRES_USER=core_synthetic \
uv run --no-sync pytest -m postgres -q
```

設定が欠落した場合はSKIPせず失敗します。各ケースは一意な`dsc_test_<ID>` schemaを作り、終了時に
そのケースで生成したschemaだけを削除します。CIではネットワーク・公開portなしの使い捨てserverへ
Unix socketで接続し、通常の品質ゲートと区別して実DB結果を確認します。

PostgreSQLの管理運用、dogfoodへの切替、既存SQLite移行、私的実会話import、実モデル評価は対象外です。
backend試験の成功をこれらの完了として扱わず、正確なrevision・環境・結果は日付付き証跡に残します。
