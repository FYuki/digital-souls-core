"""隔離 pgvector fixture だけを対象とする合成試験用の接続。"""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection

from experiments.pgvector_memory.store import PocConfig


@contextmanager
def raw_connection(config: PocConfig) -> Iterator[Connection[tuple[Any, ...]]]:
    config.__post_init__()
    if any(name.startswith("PG") and value for name, value in os.environ.items()):
        raise ValueError("Inherited libpq configuration is not permitted")
    with psycopg.connect(
        host=config.socket,
        port=config.port,
        dbname=config.database,
        user=config.user,
        password="",
        passfile="/dev/null/no-passfile",
        connect_timeout=5,
        sslmode="disable",
        gssencmode="disable",
        channel_binding="disable",
        require_auth="none",
        autocommit=True,
    ) as connection:
        yield connection
