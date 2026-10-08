"""Synthetic PostgreSQL harness; provider responses stay in process."""

from digital_souls_core.application import Inference
from digital_souls_core.conversations import Conversations
from digital_souls_core.history import Binding, SourceReference
from digital_souls_core.local_extractor import LocalExtractor
from digital_souls_core.memory import MemoryContext, MemoryService
from digital_souls_core.memory_contracts import Memory, MemoryStore
from digital_souls_core.memory_retrieval import MemoryRetrieval
from digital_souls_core.postgres_db import PostgresDatabase, key
from digital_souls_core.postgres_memory import PostgresMemory
from digital_souls_core.postgres_memory_records import PostgresMemoryRecords
from digital_souls_core.privacy import PrivacyPolicy
from digital_souls_core.privacy_classifier import LocalClassifier

from . import test_postgres_stores
from .conversation_support import turn
from .memory_support import selection as selection
from .privacy_support import BINDING, assessment, local_profile
from .record_retrieval_support import SyntheticEmbedding
from .support import FakeProvider, character
from .test_postgres_stores import Stores as Stores

stores = test_postgres_stores.stores


async def source(
    conversation: Conversations, text: str = "I like synthetic tea."
) -> SourceReference:
    cid = conversation.create("synthetic").conversation_id
    # Seeding a fixture is not an implicit memory lookup.
    context = conversation.inference.memory_context
    conversation.inference.memory_context = None
    await conversation.complete(
        "synthetic", cid, turn(messages=[{"role": "user", "content": text}])
    )
    conversation.inference.memory_context = context
    return SourceReference(cid, 1, 0)


async def assert_memoryless_turn(conversation: Conversations, query: str, stream: bool) -> None:
    provider = conversation.inference.provider
    assert isinstance(provider, FakeProvider)
    provider.calls.clear()
    cid = conversation.create("synthetic").conversation_id
    body = turn(messages=[{"role": "user", "content": query}], stream=stream)
    receipt = await conversation.complete("synthetic", cid, body)
    assert receipt.revision == 1 and receipt.message.content == "こんにちは"
    assert len(provider.calls) == 1
    assert provider.calls[0][1]["messages"] == [
        {"role": "system", "content": conversation.inference.characters["synthetic"].system_prompt},
        {"role": "user", "content": query},
    ]
    snapshot = conversation.read("synthetic", cid)
    assert snapshot.revision == 1
    assert snapshot.messages == (body.messages[0], receipt.message)
    assert conversation.store.receipt(BINDING, cid, body.request_id) == receipt


def setup(
    stores: Stores, *, local: bool = True
) -> tuple[MemoryService, Conversations, FakeProvider]:
    classifier = FakeProvider()
    classifier.response["choices"][0]["message"]["content"] = assessment()
    policy = PrivacyPolicy(
        LocalClassifier(classifier, local_profile(), model_digest="synthetic-digest")
    )
    policy.configure({BINDING: frozenset({"history", "local", "external", "memory"})})
    char = character("synthetic")
    if local:
        char = type(char)(
            char.config.model_copy(update={"profile": local_profile()}), char.system_prompt
        )
    inference = Inference((char,), FakeProvider(), privacy=policy)
    conversation = Conversations(inference, stores.history, policy)
    provider = FakeProvider()
    provider.response["choices"][0]["message"]["content"] = selection()
    service = MemoryService(
        stores.memory,
        policy,
        LocalExtractor(provider, local_profile(), model_digest="synthetic"),
    )
    conversation.inference.memory_context = MemoryContext(
        MemoryRetrieval(
            PostgresMemoryRecords(stores.database), policy, embedding=SyntheticEmbedding()
        )
    )
    return service, conversation, provider


def store(service: MemoryService) -> PostgresMemory:
    assert isinstance(service.store, PostgresMemory)
    return service.store


def reopen(stores: Stores) -> PostgresMemory:
    return PostgresMemory(PostgresDatabase(stores.config))


def assert_not_persisted(stores: Stores, marker: str) -> None:
    # PostgreSQL logical persistence; WAL/old tuples/physical media are outside this contract.
    with stores.database.transaction(BINDING) as db:
        tables = db.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema()"
        ).fetchall()
        assert tables
        from psycopg import sql

        for (table,) in tables:
            rows = db.execute(sql.SQL("SELECT * FROM {}").format(sql.Identifier(table))).fetchall()
            assert marker not in repr(rows)


def written(memory: MemoryStore, binding: Binding) -> tuple[Memory, ...]:
    """Inspect write results only; never use a removed retrieval/fallback API.

    Tests of extraction/rebuild need all completed job outputs. The SQL only
    addresses jobs; the production results port rechecks output eligibility.
    """
    assert isinstance(memory, PostgresMemory)
    with memory.database.transaction(binding) as db:
        jobs = db.execute(
            "SELECT id FROM memory_jobs WHERE binding=%s ORDER BY seq DESC", (key(binding),)
        ).fetchall()
    return tuple(m for (job_id,) in jobs for m in memory.results(binding, job_id))
