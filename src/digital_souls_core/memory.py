"""Explicit finite memory operations with current-policy and source authorization."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import replace

from .application import CoreError
from .character import AccessScope, Character, GuardedContext
from .history import Binding, SourceReference
from .local_extractor import LocalExtractor
from .memory_contracts import Memory, MemoryJob, MemoryStore, SourceVersion
from .memory_ranking import (
    EmbeddingSpace,
    MemoryEmbedding,
    RetrievalPolicy,
    rank_memories,
    validate_embedding_space,
    validate_retrieval_policy,
)
from .privacy import PrivacyPolicy
from .privacy_classifier import LocalClassifier
from .privacy_scan import scan


class MemoryQueryUnavailable(CoreError):
    """Query authorization refused/unavailable before any memory storage lookup."""

    def __init__(self) -> None:
        super().__init__(403, "memory_query_unavailable", "Memory query not authorized")


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        policy: PrivacyPolicy,
        extractor: LocalExtractor,
        *,
        embedding: MemoryEmbedding | None = None,
        retrieval: RetrievalPolicy | None = None,
    ) -> None:
        if not isinstance(policy.classifier, LocalClassifier):
            raise ValueError("memory requires managed local classification")
        self.retrieval = validate_retrieval_policy(retrieval or RetrievalPolicy())
        self.store = store
        self.policy = policy
        self.extractor = extractor
        self._embedding_generation = 0
        self.embedding = embedding

    @property
    def embedding(self) -> MemoryEmbedding | None:
        return self._embedding

    @embedding.setter
    def embedding(self, value: MemoryEmbedding | None) -> None:
        # Trusted startup injection only. Even assigning the same instance retires
        # outstanding ranking authorizations; no vector cache crosses generations.
        self._embedding = value
        self._embedding_generation += 1

    def _retrieval_stamp(self) -> tuple[int, EmbeddingSpace | None]:
        try:
            space = None if self.embedding is None else self.embedding.space
            if self.embedding is not None:
                space = validate_embedding_space(space)
                # Snapshot scalar metadata; even a trusted adapter bypassing the
                # frozen dataclass cannot mutate a previously captured stamp.
                space = replace(space)
            return self._embedding_generation, space
        except Exception:
            raise CoreError(
                502, "memory_embedding_failed", "Invalid memory embedding configuration"
            ) from None

    def _versions(self) -> str:
        if not isinstance(self.policy.classifier, LocalClassifier):
            raise CoreError(403, "memory_denied", "Managed local classifier required")
        provenance = {
            "extractor": self.extractor.provenance,
            "classifier": self.policy.classifier.provenance,
        }
        finding = scan(provenance)
        encoded = json.dumps(provenance, sort_keys=True)
        if finding.failed or finding.secret or len(encoded) > 4096:
            raise CoreError(403, "memory_denied", "Invalid memory provenance")
        return encoded

    async def extract(
        self, binding: Binding, refs: tuple[SourceReference, ...]
    ) -> tuple[Memory, ...]:
        policy = self.policy
        stamp = policy.stamp
        versions = self._versions()
        evidence = self.store.sources(binding, refs)
        if not await policy.authorize(binding, "memory", [item.text for item in evidence]):
            raise CoreError(403, "memory_denied", "Memory input denied")
        if policy is not self.policy or stamp != policy.stamp or versions != self._versions():
            raise CoreError(403, "memory_denied", "Memory policy changed")
        job = self.store.begin(binding, tuple(item.source for item in evidence), versions)
        return await self.run(binding, job)

    async def run(self, binding: Binding, job: MemoryJob) -> tuple[Memory, ...]:
        if job.state not in {"pending", "done"}:
            raise CoreError(409, "memory_job_invalid", "Explicit extraction required")
        policy, extractor = self.policy, self.extractor
        stamp = policy.stamp
        if job.versions != self._versions():
            raise CoreError(403, "memory_denied", "Memory configuration changed")
        evidence = self.store.sources(binding, tuple(s.reference for s in job.sources))
        if tuple(item.source for item in evidence) != job.sources:
            raise CoreError(409, "memory_source_invalid", "Memory source changed")
        if not await policy.authorize(binding, "memory", [item.text for item in evidence]):
            raise CoreError(403, "memory_denied", "Memory input denied")
        self._check(binding, job.sources, policy, stamp, job.versions)
        if job.state != "done":
            candidates = await extractor.extract(evidence)
            self._check(binding, job.sources, policy, stamp, job.versions)
            if not await policy.authorize(binding, "memory", [item.text for item in candidates]):
                raise CoreError(403, "memory_denied", "Memory output denied")
            self._check(binding, job.sources, policy, stamp, job.versions)
            if extractor is not self.extractor:
                raise CoreError(403, "memory_denied", "Memory extractor changed")
            self.store.commit(binding, job, candidates)
        result = self.store.results(binding, job.job_id)
        if not await policy.authorize(binding, "memory", [m.text for m in result]):
            raise CoreError(403, "memory_denied", "Memory result denied")
        self._check(binding, job.sources, policy, stamp, job.versions)
        if not self.store.valid(binding, result):
            raise CoreError(409, "memory_source_invalid", "Memory source changed")
        return result

    def _check(
        self,
        binding: Binding,
        sources: tuple[SourceVersion, ...],
        policy: PrivacyPolicy,
        stamp: tuple[int, int],
        versions: str,
    ) -> None:
        if (
            policy is not self.policy
            or policy.stamp != stamp
            or versions != self._versions()
            or not policy.permits(binding, "memory")
            or not policy.permits(binding, "local")
        ):
            raise CoreError(403, "memory_denied", "Memory policy changed")
        if not self.store.current(binding, sources):
            raise CoreError(409, "memory_source_invalid", "Memory source changed")

    async def search(
        self,
        binding: Binding,
        query: str,
        limit: int | None = None,
        *,
        authorized: Callable[[], bool] = lambda: True,
    ) -> tuple[Memory, ...]:
        """Return at most the policy count; an explicit limit may only lower it."""
        retrieval = self.retrieval
        if limit is None:
            limit = retrieval.max_retrieved_memories
        if (
            not isinstance(query, str)
            or not 0 < len(query) <= 256
            or type(limit) is not int
            or not 1 <= limit <= 16
        ):
            raise CoreError(400, "memory_query_invalid", "Invalid memory query")
        limit = min(limit, retrieval.max_retrieved_memories)
        policy, stamp, versions = self.policy, self.policy.stamp, self._versions()
        embedding, stamp_retrieval = self.embedding, self._retrieval_stamp()
        memory_store = self.store

        def check(memories: tuple[Memory, ...] = ()) -> None:
            if (
                not authorized()
                or policy is not self.policy
                or stamp != policy.stamp
                or versions != self._versions()
                or embedding is not self.embedding
                or stamp_retrieval != self._retrieval_stamp()
                or retrieval is not self.retrieval
                or memory_store is not self.store
                or (memories and not memory_store.valid(binding, memories))
            ):
                raise CoreError(403, "memory_denied", "Memory authorization changed")

        check()
        query_allowed = await policy.authorize(binding, "memory", query)
        check()
        if not query_allowed:
            raise MemoryQueryUnavailable()
        if embedding is None:
            result = memory_store.search(binding, query, limit)
        else:
            candidates = memory_store.candidates(binding)
            # No persistent index: each operation ranks only currently eligible
            # memories, and limits total text before classification or embedding.
            if len(candidates) > 1000 or sum(len(m.text.encode()) for m in candidates) > 262144:
                raise CoreError(413, "memory_limit", "Memory embedding scope exceeds limit")
            check(candidates)
            if not candidates:
                return ()
            if not await policy.authorize(binding, "memory", [m.text for m in candidates]):
                raise CoreError(403, "memory_denied", "Memory candidates denied")
            check(candidates)
            try:
                async with asyncio.timeout(15):
                    vectors = await embedding.embed((query, *(m.text for m in candidates)))
            except Exception:
                raise CoreError(502, "memory_embedding_failed", "Memory embedding failed") from None
            check(candidates)
            space = stamp_retrieval[1]
            assert space is not None
            result = rank_memories(candidates, vectors, space, retrieval)[:limit]
        if not await policy.authorize(binding, "memory", [m.text for m in result]):
            raise CoreError(403, "memory_denied", "Memory result denied")
        check(candidates if embedding is not None else result)
        return result

    async def rebuild(self, binding: Binding, *, limit: int = 16) -> int:
        """Finite drain; isolate failed work without migrating approved configuration."""
        for event in self.store.events(binding):
            self.store.consume(binding, event)
        completed = 0
        failed = False
        for job in self.store.pending(binding, limit):
            current = self.store.rebase(binding, job)
            if current is not None:
                try:
                    await self.run(binding, current)
                except CoreError:
                    self.store.fail(binding, current)
                    failed = True
                else:
                    completed += 1
        if failed:
            raise CoreError(
                409, "memory_rebuild_incomplete", "Some memory jobs require explicit extraction"
            )
        return completed


class MemoryContext:
    """Opt-in conversation-only context carrying an authorization guard until dispatch."""

    def __init__(self, service: MemoryService) -> None:
        self.service = service

    @property
    def policy(self) -> PrivacyPolicy:
        return self.service.policy

    async def context(
        self,
        character: Character,
        scope: AccessScope,
        user_text: str,
        *,
        authorized: Callable[[], bool],
    ) -> GuardedContext:
        binding = Binding(scope, character.config.character_id)
        policy, stamp, versions = (
            self.service.policy,
            self.service.policy.stamp,
            self.service._versions(),
        )
        retrieval = self.service._retrieval_stamp()
        memory_store = self.service.store
        memories: tuple[Memory, ...] = ()
        if user_text and policy.permits(binding, "memory"):
            try:
                memories = await self.service.search(
                    binding, user_text[:256], authorized=authorized
                )
            except MemoryQueryUnavailable:
                # Only pre-lookup query refusal is optional. Changed policy,
                # invalid provenance, storage/result errors and cancellation propagate.
                pass
        # Opaque storage identifiers are not model evidence. Use request-local
        # references while retaining the real identities in the dispatch guard.
        conversation_refs: dict[str, str] = {}
        for memory in memories:
            for source in memory.sources:
                cid = source.reference.conversation_id
                if cid not in conversation_refs:
                    conversation_refs[cid] = f"conversation-{len(conversation_refs) + 1}"
        # Keep immutable memory/source objects in the closure after serialization.
        text = (
            json.dumps(
                [
                    {
                        "memory_ref": f"memory-{index + 1}",
                        "kind": m.kind,
                        "user_evidence": json.loads(m.text),
                        "sources": [
                            {
                                "conversation_ref": conversation_refs[
                                    source.reference.conversation_id
                                ],
                                "turn_revision": source.reference.turn_revision,
                                "message_index": source.reference.message_index,
                                "epoch": source.epoch,
                            }
                            for source in m.sources
                        ],
                    }
                    for index, m in enumerate(memories)
                ],
                ensure_ascii=False,
            )
            if memories
            else ""
        )

        def valid() -> bool:
            return (
                authorized()
                and self.service.policy is policy
                and policy.stamp == stamp
                and self.service._versions() == versions
                and self.service._retrieval_stamp() == retrieval
                and self.service.store is memory_store
                and (
                    not memories
                    or (
                        policy.permits(binding, "memory")
                        and policy.permits(binding, "local")
                        and self.service.store.valid(binding, memories)
                    )
                )
            )

        return GuardedContext(text, valid, policy)
