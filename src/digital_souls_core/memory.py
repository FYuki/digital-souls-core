"""Explicit finite memory operations with current-policy and source authorization."""

import json
from collections.abc import Callable

from .application import CoreError
from .character import AccessScope, Character, GuardedContext
from .history import Binding, SourceReference
from .local_extractor import LocalExtractor
from .memory_contracts import Memory, MemoryJob, MemoryStore, SourceVersion
from .memory_record_store import RetrievalCandidate
from .memory_records import Episode, PartialDateTime, TemporalValue
from .memory_retrieval import MemoryQueryUnavailable as MemoryQueryUnavailable
from .memory_retrieval import MemoryRetrieval
from .privacy import PrivacyPolicy
from .privacy_classifier import LocalClassifier
from .privacy_scan import scan


class MemoryService:
    def __init__(
        self,
        store: MemoryStore,
        policy: PrivacyPolicy,
        extractor: LocalExtractor,
    ) -> None:
        if not isinstance(policy.classifier, LocalClassifier):
            raise ValueError("memory requires managed local classification")
        self.store = store
        self.policy = policy
        self.extractor = extractor

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


def _time(value: TemporalValue) -> dict[str, object]:
    def partial(v: PartialDateTime | None) -> dict[str, object] | None:
        if v is None:
            return None
        return {
            "precision": v.precision.value,
            **{
                k: getattr(v, k)
                for k in ("year", "month", "day", "hour", "minute", "second")
                if getattr(v, k) is not None
            },
        }

    return {"start": partial(value.start), "end": partial(value.end), "timezone": value.timezone}


class MemoryContext:
    """Opt-in conversation-only context carrying an authorization guard until dispatch."""

    def __init__(self, service: MemoryRetrieval) -> None:
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
        policy = self.service.policy
        stamp = policy.stamp
        memories: tuple[RetrievalCandidate, ...] = ()
        try:
            versions = self.service._classifier()
            retrieval = self.service._retrieval_stamp()
            memory_store = self.service.records
            ranking = self.service.retrieval
            ranking_stamp = self.service._ranking_stamp()
            if user_text and policy.permits(binding, "memory"):
                memories = await self.service.search(
                    binding, user_text[:256], authorized=authorized
                )
        except CoreError:
            # Failed retrieval is optional, but conversation authorization remains
            # pinned before lookup; discarded memory/configuration is not reused.
            return GuardedContext(
                "",
                lambda: (authorized() and self.service.policy is policy and policy.stamp == stamp),
                policy,
            )
        # Opaque storage identifiers are not model evidence. Use request-local
        # references while retaining the real identities in the dispatch guard.
        conversation_refs: dict[str, str] = {}
        for memory in memories:
            for citation in memory.citations:
                source = citation.source
                cid = source.reference.conversation_id
                if cid not in conversation_refs:
                    conversation_refs[cid] = f"conversation-{len(conversation_refs) + 1}"
        # Keep immutable memory/source objects in the closure after serialization.
        text = (
            json.dumps(
                [
                    {
                        "memory_ref": f"memory-{index + 1}",
                        "kind": "episode" if isinstance(m.record, Episode) else "semantic",
                        "text": m.record.normalized_text,
                        **(
                            {"experience_time": _time(m.record.experience_time)}
                            if isinstance(m.record, Episode)
                            else {"applicability": _time(m.record.applicability)}
                        ),
                        "facts": [
                            {"text": f.normalized_text, "target_time": _time(f.target_time)}
                            for f in m.facts
                        ],
                        "sources": [
                            {
                                "conversation_ref": conversation_refs[
                                    source.reference.conversation_id
                                ],
                                "turn_revision": source.reference.turn_revision,
                                "message_index": source.reference.message_index,
                                "epoch": source.epoch,
                            }
                            for source in dict.fromkeys(c.source for c in m.citations)
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
            try:
                self.service._classifier()
                return (
                    authorized()
                    and self.service.policy is policy
                    and policy.stamp == stamp
                    and self.service._classifier() == versions
                    and self.service.retrieval is ranking
                    and self.service._ranking_stamp() == ranking_stamp
                    and self.service._retrieval_stamp() == retrieval
                    and self.service.records is memory_store
                    and (
                        not memories
                        or (
                            policy.permits(binding, "memory")
                            and policy.permits(binding, "local")
                            and memory_store.current(binding, memories)
                        )
                    )
                )
            except CoreError:
                return False

        return GuardedContext(text, valid, policy)
