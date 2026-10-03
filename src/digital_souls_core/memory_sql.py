"""Shared SQLite transactions for source changes and durable memory revocation."""

import sqlite3
from uuid import uuid4


def initialize(db: sqlite3.Connection) -> None:
    db.execute("ALTER TABLE conversations ADD COLUMN memory_epoch INTEGER NOT NULL DEFAULT 0")
    db.execute("""CREATE TABLE memory_events (
        id TEXT PRIMARY KEY, binding TEXT NOT NULL, conversation TEXT NOT NULL,
        epoch INTEGER NOT NULL, reason TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0
    )""")
    db.execute("""CREATE TABLE memory_jobs (
        id TEXT NOT NULL, binding TEXT NOT NULL, sources TEXT NOT NULL, versions TEXT NOT NULL,
        state TEXT NOT NULL, PRIMARY KEY(binding,id)
    )""")
    db.execute("""CREATE TABLE memories (
        id TEXT NOT NULL, binding TEXT NOT NULL, job TEXT NOT NULL, kind TEXT NOT NULL,
        body TEXT, state TEXT NOT NULL, revoked_by TEXT,
        PRIMARY KEY(binding,id), FOREIGN KEY(binding,job) REFERENCES memory_jobs(binding,id)
    )""")
    db.execute("""CREATE TABLE memory_sources (
        binding TEXT NOT NULL, memory TEXT NOT NULL, conversation TEXT NOT NULL,
        revision INTEGER NOT NULL, position INTEGER NOT NULL, epoch INTEGER NOT NULL,
        PRIMARY KEY(binding,memory,conversation,revision,position),
        FOREIGN KEY(binding,memory) REFERENCES memories(binding,id) ON DELETE CASCADE
    )""")
    db.execute("CREATE INDEX memory_source_lookup ON memory_sources(binding,conversation)")
    db.execute("PRAGMA user_version=3")


def revoke(
    db: sqlite3.Connection, binding: str, conversation: str, epoch: int, reason: str
) -> None:
    event = str(uuid4())
    db.execute(
        "INSERT INTO memory_events(id,binding,conversation,epoch,reason) VALUES (?,?,?,?,?)",
        (event, binding, conversation, epoch, reason),
    )
    # No text index or cache exists. Erase the only stored body in the source
    # transaction, even if the optional rebuild consumer is stopped indefinitely.
    db.execute(
        "UPDATE memories SET body=NULL,state='revoked',revoked_by=? "
        "WHERE binding=? AND state='active' AND id IN "
        "(SELECT memory FROM memory_sources WHERE binding=? AND conversation=?)",
        (event, binding, binding, conversation),
    )
