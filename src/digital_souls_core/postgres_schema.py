"""Version-one PostgreSQL schema and atomic source revocation."""

from typing import Any
from uuid import uuid4

from psycopg import Connection

TABLE_COLUMNS = {
    "schema_version": ("version",),
    "conversations": (
        "seq",
        "binding",
        "id",
        "revision",
        "private_mode",
        "archived",
        "memory_epoch",
    ),
    "turns": (
        "seq",
        "binding",
        "conversation",
        "request",
        "fingerprint",
        "revision",
        "messages",
        "finish",
        "memory_excluded",
        "private_mode",
    ),
    "source_deletions": ("seq", "event", "binding", "conversation", "through_revision"),
    "memory_events": ("seq", "id", "binding", "conversation", "epoch", "reason", "processed"),
    "memory_jobs": ("seq", "id", "binding", "sources", "versions", "state"),
    "memories": ("seq", "id", "binding", "job", "kind", "body", "state", "revoked_by"),
    "memory_sources": ("seq", "binding", "memory", "conversation", "revision", "position", "epoch"),
}

# These are the keys and referential actions on which receipt and deletion guarantees rely.
CONSTRAINTS = {
    ("schema_version", "schema_version_pkey"): "PRIMARY KEY (version)",
    ("conversations", "conversations_pkey"): "PRIMARY KEY (binding, id)",
    ("turns", "turns_pkey"): "PRIMARY KEY (binding, conversation, request)",
    (
        "turns",
        "turns_binding_conversation_revision_key",
    ): "UNIQUE (binding, conversation, revision)",
    (
        "turns",
        "turns_binding_conversation_fkey",
    ): (
        "FOREIGN KEY (binding, conversation) REFERENCES conversations(binding, id) "
        "ON DELETE CASCADE"
    ),
    ("source_deletions", "source_deletions_pkey"): "PRIMARY KEY (event)",
    ("memory_events", "memory_events_pkey"): "PRIMARY KEY (id)",
    ("memory_jobs", "memory_jobs_pkey"): "PRIMARY KEY (binding, id)",
    ("memories", "memories_pkey"): "PRIMARY KEY (binding, id)",
    (
        "memories",
        "memories_binding_job_fkey",
    ): "FOREIGN KEY (binding, job) REFERENCES memory_jobs(binding, id)",
    (
        "memory_sources",
        "memory_sources_pkey",
    ): 'PRIMARY KEY (binding, memory, conversation, revision, "position")',
    (
        "memory_sources",
        "memory_sources_binding_memory_fkey",
    ): "FOREIGN KEY (binding, memory) REFERENCES memories(binding, id) ON DELETE CASCADE",
}
CONSTRAINTS.update(
    {
        (table, table + "_seq_key"): "UNIQUE (seq)"
        for table in TABLE_COLUMNS
        if table != "schema_version"
    }
)

DDL = (
    "CREATE TABLE schema_version (version INTEGER PRIMARY KEY)",
    """CREATE TABLE conversations (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        binding TEXT NOT NULL, id TEXT NOT NULL, revision INTEGER NOT NULL,
        private_mode BOOLEAN NOT NULL DEFAULT false, archived BOOLEAN NOT NULL DEFAULT false,
        memory_epoch INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(binding,id)
    )""",
    """CREATE TABLE turns (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        binding TEXT NOT NULL, conversation TEXT NOT NULL, request TEXT NOT NULL,
        fingerprint TEXT NOT NULL, revision INTEGER NOT NULL, messages TEXT NOT NULL,
        finish TEXT NOT NULL, memory_excluded TEXT NOT NULL DEFAULT '[]',
        private_mode BOOLEAN NOT NULL DEFAULT false,
        PRIMARY KEY(binding,conversation,request), UNIQUE(binding,conversation,revision),
        FOREIGN KEY(binding,conversation) REFERENCES conversations(binding,id) ON DELETE CASCADE
    )""",
    """CREATE TABLE source_deletions (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        event TEXT PRIMARY KEY, binding TEXT NOT NULL, conversation TEXT NOT NULL,
        through_revision INTEGER NOT NULL
    )""",
    """CREATE TABLE memory_events (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        id TEXT PRIMARY KEY, binding TEXT NOT NULL, conversation TEXT NOT NULL,
        epoch INTEGER NOT NULL, reason TEXT NOT NULL, processed BOOLEAN NOT NULL DEFAULT false
    )""",
    """CREATE TABLE memory_jobs (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        id TEXT NOT NULL, binding TEXT NOT NULL, sources TEXT NOT NULL, versions TEXT NOT NULL,
        state TEXT NOT NULL, PRIMARY KEY(binding,id)
    )""",
    """CREATE TABLE memories (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        id TEXT NOT NULL, binding TEXT NOT NULL, job TEXT NOT NULL, kind TEXT NOT NULL,
        body TEXT, state TEXT NOT NULL, revoked_by TEXT,
        PRIMARY KEY(binding,id), FOREIGN KEY(binding,job) REFERENCES memory_jobs(binding,id)
    )""",
    """CREATE TABLE memory_sources (
        seq BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
        binding TEXT NOT NULL, memory TEXT NOT NULL, conversation TEXT NOT NULL,
        revision INTEGER NOT NULL, position INTEGER NOT NULL, epoch INTEGER NOT NULL,
        PRIMARY KEY(binding,memory,conversation,revision,position),
        FOREIGN KEY(binding,memory) REFERENCES memories(binding,id) ON DELETE CASCADE
    )""",
    "CREATE INDEX memory_source_lookup ON memory_sources(binding,conversation)",
    "INSERT INTO schema_version(version) VALUES (1)",
)


def create(db: Connection[tuple[Any, ...]]) -> None:
    for statement in DDL:
        db.execute(statement)


def revoke(
    db: Connection[tuple[Any, ...]],
    binding: str,
    conversation: str,
    epoch: int,
    reason: str,
) -> None:
    event = str(uuid4())
    db.execute(
        "INSERT INTO memory_events(id,binding,conversation,epoch,reason) VALUES (%s,%s,%s,%s,%s)",
        (event, binding, conversation, epoch, reason),
    )
    db.execute(
        "UPDATE memories SET body=NULL,state='revoked',revoked_by=%s "
        "WHERE binding=%s AND state='active' AND id IN "
        "(SELECT memory FROM memory_sources WHERE binding=%s AND conversation=%s)",
        (event, binding, binding, conversation),
    )
