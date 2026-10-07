# ローカルDocker PostgreSQLの検証（2026-10-07）

対象: [Issue #85](https://github.com/FYuki/digital-souls-core/issues/85)。
実装revision: `9e428f9bc795a2d96b3578cedd91f12986eb0c8f`。
基点: `67baa92890de6803c6a4ff44f16391e55c1fe638`、branch: `infra/85-local-postgres`。
この証跡は実装revisionの検証後に追加した文書で、製品コードの変更を含みません。

環境: Linux、Python 3.12.3、uv 0.8.22、Node 24.19.0、Docker client/server 29.6.0、
Docker Compose v5.2.0。指定の固定toolchainをPATHの先頭に置き、全試験を`TMPDIR=/dev/shm`で実行しました。
`LITELLM_LOCAL_MODEL_COST_MAP=True`を設定し、実LLM・実会話・運用資格情報は使っていません。
公式imageは取得済みのdigest固定PostgreSQL 18です。

## TDD

先に`tools/check-docs.test.mjs`へ4件の要件検査を追加しました。

```sh
TMPDIR=/dev/shm node --test --test-name-pattern='local PostgreSQL' tools/check-docs.test.mjs
```

- 実装前: **FAIL 4件 / PASS 0件**。Compose定義が存在せず`ENOENT`。
- 実装後: **PASS 4件 / FAIL 0件**。skip・todo・cancelledは0件。
- 検査対象: 合成試験と同じimage/digest、loopback限定の公開、named volumeの保存先、
  必須の資格情報変数・空の例ファイル・ローカル環境ファイルのGit除外。
- `.gitignore`は既存の`.env.*`で`.env.postgresql.local`を除外します。追加変更は不要でした。

## Docker実起動・認証・schema初期化

以下を実装revisionでローカル実行しました。パスワードはメモリ内で生成した一時合成値で、
ファイル・ログ・証跡へ保存していません。公開portは空きportを動的選択しました。
Compose projectはランダムな専用名とし、既存のDB・volumeへ接続していません。

```sh
TMPDIR=/dev/shm LITELLM_LOCAL_MODEL_COST_MAP=True uv run --no-sync python - <<'PY'
import os, secrets, socket, subprocess
from pydantic import SecretStr
from digital_souls_core.postgres_db import PostgresConfig, PostgresDatabase
from digital_souls_core.storage import StorageConfig, open_storage
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
env = dict(os.environ, DSC_POSTGRES_DATABASE='core_synthetic', DSC_POSTGRES_USER='core_synthetic',
           DSC_POSTGRES_PASSWORD=secrets.token_urlsafe(32), DSC_POSTGRES_PORT=str(port))
project = 'dsc-local-85-' + secrets.token_hex(4)
command = ['docker', 'compose', '-p', project, '-f', 'compose.postgresql.json']
def compose(*args):
    subprocess.run(command + list(args), env=env, check=True)
config = PostgresConfig(host='127.0.0.1', port=port, database=env['DSC_POSTGRES_DATABASE'],
                        user=env['DSC_POSTGRES_USER'], password=SecretStr(env['DSC_POSTGRES_PASSWORD']),
                        schema_name='local_synthetic')
try:
    compose('config', '--quiet')
    compose('up', '-d', '--wait')
    open_storage(StorageConfig(backend='postgresql', postgres=config))
    db = PostgresDatabase(config)
    with db._connect() as conn:
        count = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'local_synthetic'").fetchone()[0]
    assert count > 0
    print(f'PASS: PostgresConfig / open_storage initialized schema; {count} tables', flush=True)
    compose('down')
    compose('up', '-d', '--wait')
    db.initialize()
    with db._connect() as conn:
        assert conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'local_synthetic'").fetchone()[0] == count
    print('PASS: named volume schema survives stop / restart', flush=True)
finally:
    compose('down', '--volumes')
    remaining = subprocess.check_output(['docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}'], text=True)
    volumes = subprocess.check_output(['docker', 'volume', 'ls', '-q', '--filter', f'label=com.docker.compose.project={project}'], text=True)
    assert not remaining.strip() and not volumes.strip()
    print('PASS: containers and named volume removed', flush=True)
PY
```

結果: **PASS 3確認**、exit code 0。

1. Composeがhealthyになり、TCPのloopback接続で`open_storage`がschemaを初期化（19表）。
2. `down`後に再起動し、`PostgresDatabase.initialize()`が既存schemaを厳密照合して再利用（19表を保持）。
3. `down --volumes`後に当該projectのコンテナ・named volumeが0件。専用networkも削除。

## 品質ゲート

| コマンド | 結果・件数 |
| --- | --- |
| `uv sync --frozen` | PASS、78 packageをinstall、lock変更なし |
| `uv run --no-sync ruff check src tests tools/evaluate-memory-search.py` | PASS、指摘0件 |
| `uv run --no-sync ruff format --check src tests tools/evaluate-memory-search.py` | PASS、88ファイル |
| `uv run --no-sync mypy` | PASS、88 source files、指摘0件 |
| `uv run --no-sync pytest -m ut -q` | PASS、477 passed、1107 deselected、1 warning |
| `uv run --no-sync pytest -m it1 -q` | PASS、863 passed、721 deselected、3 warnings |
| `uv build --no-build-isolation` | PASS、sdist・wheelの2成果物 |
| `bash tools/test-postgres.sh` | PASS、244 passed、1340 deselected、1 warning。既存scriptは無変更 |
| `node --test --test-reporter=./tools/required-tests-reporter.mjs tools/check-docs.test.mjs tools/required-tests-reporter.test.mjs` | PASS、27登録テスト、skip・todo・cancelled 0件 |
| `docker compose -f compose.postgresql.json config --no-interpolate --quiet` | PASS、1定義 |
| `node tools/check-docs.mjs` | PASS、81対象ファイル、指摘0件 |
| `git diff --check` | PASS、指摘0件 |

pytestのdeselectedはmarkerで対象外とした試験で、skipではありません。
warningは既存依存のStarlette/AnyIO非推奨通知とPydanticのReadOnly通知です。

CIには新しいjobを追加せず、既存`postgres-storage`にCompose構文検査stepを追加しました。
要件検査4件は既存`docs-tooling`で実行される試験群に含まれます。
required check名・常時実行条件は変更していません。
GitHub上のCIは **NOT RUN**（push・PR作成を行っていないため）。
ローカル用Composeの実起動・TCP接続はCIでは **NOT RUN**。
実運用・実モデルのIT2/STは **NOT RUN** で、この合成試験のPASSから推定しません。

確認事項: 要件の解釈に関する未決事項はありません。GitHub CIの確認は監督のpush後に必要です。
