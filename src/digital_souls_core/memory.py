"""Explicit finite memory operations with current-policy and source authorization."""

import json
from collections.abc import Callable

from .application import CoreError
from .character import AccessScope, Character, GuardedContext
from .history import Binding, SourceReference
from .local_extractor import LocalExtractor
from .memory_contracts import Memory, MemoryJob, MemoryStore, SourceVersion
from .privacy import PrivacyPolicy
from .privacy_classifier import LocalClassifier
from .privacy_scan import scan


class MemoryService:
    def __init__(
        self, store: MemoryStore, policy: PrivacyPolicy, extractor: LocalExtractor
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
        limit: int = 8,
        *,
        authorized: Callable[[], bool] = lambda: True,
    ) -> tuple[Memory, ...]:
        policy, stamp, versions = self.policy, self.policy.stamp, self._versions()
        if not authorized():
            raise CoreError(403, "memory_denied", "Memory caller authorization changed")
        if not await policy.authorize(binding, "memory", query):
            raise CoreError(403, "memory_denied", "Memory query denied")
        if (
            not authorized()
            or policy is not self.policy
            or stamp != policy.stamp
            or versions != self._versions()
        ):
            raise CoreError(403, "memory_denied", "Memory policy changed")
        result = self.store.search(binding, query, limit)
        if not await policy.authorize(binding, "memory", [m.text for m in result]):
            raise CoreError(403, "memory_denied", "Memory result denied")
        if (
            policy is not self.policy
            or stamp != policy.stamp
            or versions != self._versions()
            or not self.store.valid(binding, result)
            or not authorized()
        ):
            raise CoreError(403, "memory_denied", "Memory result changed")
        return result

    async def rebuild(self, binding: Binding, *, limit: int = 16) -> int:
        """Finite trusted drain; no background worker, retries preserve pending work."""
        for event in self.store.events(binding):
            self.store.consume(binding, event)
        completed = 0
        for job in self.store.pending(binding, limit):
            current = self.store.rebase(binding, job)
            if current is not None:
                await self.run(binding, current)
                completed += 1
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
        memories = (
            await self.service.search(binding, user_text[:256], limit=4, authorized=authorized)
            if user_text
            else ()
        )
        # Keep immutable memory/source objects in the closure after serialization.
        text = (
            json.dumps(
                [
                    {"memory_id": m.memory_id, "kind": m.kind, "user_evidence": json.loads(m.text)}
                    for m in memories
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
                and policy.permits(binding, "memory")
                and policy.permits(binding, "local")
                and self.service.store.valid(binding, memories)
            )

        return GuardedContext(text, valid, policy)
