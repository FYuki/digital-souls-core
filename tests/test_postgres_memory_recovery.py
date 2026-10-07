"""Outbox processing interruption must roll back and remain retryable."""

import pytest

from digital_souls_core.application import CoreError

from . import postgres_memory_support
from .postgres_memory_support import Stores, reopen, selection, setup, source
from .privacy_support import BINDING

stores = postgres_memory_support.stores
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("stage", ["job_insert", "event_processed"])
async def test_interrupted_outbox_consume_replays_atomically(stores: Stores, stage: str) -> None:
    service, conversation, provider = setup(stores)
    refs = (
        await source(conversation, "Synthetic alpha"),
        await source(conversation, "Synthetic beta"),
    )
    provider.response["choices"][0]["message"]["content"] = selection([0, 1])
    old = await service.extract(BINDING, refs)
    conversation.delete("synthetic", refs[0].conversation_id)
    event = service.store.events(BINDING)[0]
    remaining = conversation.read("synthetic", refs[1].conversation_id)
    with stores.database.transaction(BINDING) as db:
        db.execute(
            "CREATE FUNCTION interrupt_consume() RETURNS trigger LANGUAGE plpgsql AS "
            "$$ BEGIN RAISE EXCEPTION 'synthetic interruption'; END $$"
        )
        if stage == "job_insert":
            db.execute(
                "CREATE TRIGGER interrupt_consume BEFORE INSERT ON memory_jobs "
                "FOR EACH ROW EXECUTE FUNCTION interrupt_consume()"
            )
        else:
            db.execute(
                "CREATE TRIGGER interrupt_consume BEFORE UPDATE OF processed ON memory_events "
                "FOR EACH ROW EXECUTE FUNCTION interrupt_consume()"
            )
    with pytest.raises(CoreError):
        service.store.consume(BINDING, event)
    assert conversation.read("synthetic", refs[1].conversation_id) == remaining
    assert not service.store.valid(BINDING, old)
    assert service.store.search(BINDING, "alpha") == ()
    assert service.store.events(BINDING) == (event,)
    assert service.store.pending(BINDING) == ()
    with stores.database.transaction(BINDING) as db:
        assert db.execute("SELECT body,state FROM memories").fetchall() == [(None, "revoked")]
        assert db.execute("SELECT processed FROM memory_events").fetchall() == [(False,)]
        assert db.execute("SELECT COUNT(*) FROM memory_jobs").fetchone() == (1,)
        table = "memory_jobs" if stage == "job_insert" else "memory_events"
        from psycopg import sql

        db.execute(sql.SQL("DROP TRIGGER interrupt_consume ON {}").format(sql.Identifier(table)))
        db.execute("DROP FUNCTION interrupt_consume()")
    service.store = reopen(stores)
    service.store.consume(BINDING, event)
    service.store.consume(BINDING, event)
    pending = service.store.pending(BINDING)
    assert len(pending) == 1 and tuple(s.reference for s in pending[0].sources) == (refs[1],)
    provider.calls.clear()
    provider.response["choices"][0]["message"]["content"] = selection()
    assert await service.rebuild(BINDING) == 1
    result = await service.search(BINDING, "beta")
    assert result[0].memory_id != old[0].memory_id
    assert result[0].sources[0].reference == refs[1] and result[0].sources[0].epoch == 0
    assert "alpha" not in result[0].text
    assert "alpha" not in repr(provider.calls)
    assert service.store.events(BINDING) == () and service.store.pending(BINDING) == ()
    assert await service.rebuild(BINDING) == 0
