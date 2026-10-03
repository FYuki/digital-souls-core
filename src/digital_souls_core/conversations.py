"""Opt-in stateful path; the existing Inference API remains stateless."""

import hashlib
import json
from contextlib import aclosing
from typing import Any

from pydantic import ValidationError

from .application import CoreError, Inference
from .character import CharacterConfig, Profile
from .contracts import CompletionInput, Message
from .history import Binding, HistoryPolicy, HistoryStore, Operation, Receipt, Snapshot, TurnInput

MAX_BYTES = 1024 * 1024


def bounded(value: object) -> None:
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_BYTES:
        raise CoreError(413, "history_limit", "Conversation byte limit exceeded")


def request_fingerprint(body: TurnInput, config: CharacterConfig) -> str:
    profile = config.profile.model_dump(mode="json")
    profile["allowed_parameters"] = sorted(config.profile.allowed_parameters)
    return hashlib.sha256(
        json.dumps(
            [body.model_dump(), config.config_version, profile],
            sort_keys=True,
        ).encode()
    ).hexdigest()


class Conversations:
    def __init__(
        self, inference: Inference, store: HistoryStore, policy: HistoryPolicy | None = None
    ) -> None:
        self.inference = inference
        self.store = store
        self.policy = policy

    def binding(self, character_id: str) -> Binding:
        if character_id not in self.inference.characters:
            raise CoreError(404, "character_not_found", "Unknown character")
        return Binding(self.inference.scope, character_id)

    def authorize(
        self, operation: Operation, binding: Binding, messages: tuple[Message, ...] = ()
    ) -> None:
        try:
            allowed = (
                self.policy is not None
                and self.policy.allows(
                    operation, binding, tuple(m.model_copy(deep=True) for m in messages)
                )
                is True
            )
        except Exception:
            allowed = False
        if not allowed:
            raise CoreError(403, "history_policy_denied", "History policy denies operation")

    def create(self, character_id: str) -> Snapshot:
        binding = self.binding(character_id)
        self.authorize("create", binding)
        return self.store.create(binding)

    def list(self, character_id: str) -> list[str]:
        binding = self.binding(character_id)
        self.authorize("list", binding)
        return self.store.list(binding)

    def read(self, character_id: str, conversation_id: str) -> Snapshot:
        binding = self.binding(character_id)
        self.authorize("read", binding)
        snapshot = self.store.read(binding, conversation_id)
        self.authorize("read", binding, snapshot.messages)
        return snapshot

    def delete(self, character_id: str, conversation_id: str) -> None:
        self.store.delete(self.binding(character_id), conversation_id)

    async def complete(self, character_id: str, conversation_id: str, body: TurnInput) -> Receipt:
        binding = self.binding(character_id)
        incoming = tuple(body.messages)
        if any(message.role not in ("user", "tool") for message in incoming):
            raise CoreError(400, "invalid_turn", "Only new user or tool messages are accepted")
        bounded(body.model_dump())
        self.authorize("store", binding, incoming)
        snapshot = self.read(character_id, conversation_id)
        config = self.inference.characters[character_id].config
        fingerprint = request_fingerprint(body, config)
        prior = self.store.receipt(binding, conversation_id, body.request_id)
        if prior is not None:
            if prior.fingerprint != fingerprint:
                raise CoreError(409, "request_conflict", "Request id has different input")
            self.authorize("read", binding, (prior.message,))
            return prior
        if snapshot.revision != body.expected_revision:
            raise CoreError(409, "revision_conflict", "Conversation revision changed")
        all_input = (*snapshot.messages, *incoming)
        payload = body.model_dump(exclude={"request_id", "expected_revision"}, exclude_none=True)
        payload["messages"] = [m.model_dump(exclude_none=True) for m in all_input]
        bounded(payload)
        try:
            request = CompletionInput.model_validate(payload)
        except ValidationError:
            raise CoreError(400, "invalid_turn", "Invalid conversation or tool sequence") from None
        self.authorize("export", binding, all_input)
        prepared = await self.inference.prepare(character_id, request, alias=False)
        profile = prepared.character.config.profile
        self.authorize("export", binding, all_input)
        try:
            if body.stream:
                message, finish = await self._stream(profile, prepared.payload)
            else:
                result = await self.inference.provider.complete(profile, prepared.payload)
                choices = result["choices"]
                if len(choices) != 1 or choices[0]["index"] != 0:
                    raise ValueError("one choice required")
                finish = choices[0]["finish_reason"]
                message = self._visible(choices[0]["message"])
            self._validate_result(request, message, finish)
        except CoreError:
            raise
        except Exception:
            raise CoreError(
                502, "invalid_history_result", "Provider result cannot be saved"
            ) from None
        stored = (*incoming, message)
        bounded([m.model_dump() for m in (*snapshot.messages, *stored)])
        # Re-evaluate after await: consent can be revoked while inference is active.
        self.authorize("store", binding, (*snapshot.messages, *stored))
        self.authorize("read", binding, (message,))
        return self.store.append(
            binding,
            conversation_id,
            body.request_id,
            fingerprint,
            snapshot.revision,
            stored,
            finish,
        )

    @staticmethod
    def _visible(raw: dict[str, Any]) -> Message:
        # Allowlist only the public assistant message. Never persist SDK envelopes,
        # reasoning_content, thinking, usage, credentials, injected prompts or errors.
        message = Message.model_validate(
            {
                k: v
                for k, v in raw.items()
                if k in {"role", "content", "tool_calls"} and v is not None
            }
        )
        if message.role != "assistant":
            raise ValueError("assistant required")
        if message.content and any(
            marker in message.content.casefold() for marker in ("<think", "</think", "<analysis")
        ):
            raise ValueError("embedded reasoning is not history")
        return message

    @staticmethod
    def _validate_result(request: CompletionInput, message: Message, finish: str) -> None:
        if finish not in ("stop", "tool_calls") or (finish == "tool_calls") != bool(
            message.tool_calls
        ):
            raise ValueError("incomplete or inconsistent provider result")
        names = {tool.function.name for tool in request.tools or []}
        if any(call.function.name not in names for call in message.tool_calls or []):
            raise ValueError("unknown tool")
        # Validate the complete sequence, allowing only the final assistant's pending calls.
        validation_tail = [
            Message(role="tool", tool_call_id=call.id, content="")
            for call in message.tool_calls or []
        ]
        CompletionInput(messages=[*request.messages, message, *validation_tail])

    async def _stream(self, profile: Profile, payload: dict[str, Any]) -> tuple[Message, str]:
        text = ""
        calls: dict[int, dict[str, Any]] = {}
        finish: str | None = None
        # Bounded buffering permits policy checks over complete tool arguments.
        # No partial result reaches disk or the conversation HTTP response.
        async with aclosing(self.inference.provider.stream(profile, payload)) as upstream:
            async for chunk in upstream:
                choices = chunk["choices"]
                if not choices:  # usage-only final chunk
                    continue
                if finish is not None or len(choices) != 1 or choices[0]["index"] != 0:
                    raise ValueError("invalid stream order")
                delta = choices[0]["delta"]
                if delta.get("role", "assistant") != "assistant":
                    raise ValueError("invalid role")
                text += delta.get("content") or ""
                for part in delta.get("tool_calls") or []:
                    index = part["index"]
                    if type(index) is not int or not 0 <= index < 128:
                        raise ValueError("invalid tool index")
                    call = calls.setdefault(
                        index,
                        {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
                    )
                    if part.get("type", "function") != "function":
                        raise ValueError("invalid tool type")
                    call["id"] += part.get("id") or ""
                    for field in ("name", "arguments"):
                        call["function"][field] += (part.get("function") or {}).get(field) or ""
                bounded([text, calls])
                finish = choices[0].get("finish_reason")
        if finish is None or sorted(calls) != list(range(len(calls))):
            raise ValueError("unfinished stream")
        raw: dict[str, Any] = {"role": "assistant", "content": text}
        if calls:
            raw["tool_calls"] = list(calls.values())
        return self._visible(raw), finish
