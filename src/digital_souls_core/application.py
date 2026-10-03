"""One inference path shared by both HTTP entry points."""

from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Protocol

from .character import AccessScope, Character, ContextSource, EmptyContext, Profile
from .contracts import CompletionInput
from .history import Binding
from .privacy import PrivacyPolicy, destination


class CoreError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message
        super().__init__(message)


class Provider(Protocol):
    async def complete(self, profile: Profile, payload: dict[str, Any]) -> dict[str, Any]: ...

    def stream(
        self, profile: Profile, payload: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any]]: ...


@dataclass(frozen=True)
class Prepared:
    character: Character
    payload: dict[str, Any]

    @property
    def headers(self) -> dict[str, str]:
        config = self.character.config
        return {
            "X-Character-ID": config.character_id,
            "X-Character-Config-Version": config.config_version,
            "X-Inference-Profile": config.profile.profile_id,
        }


class Inference:
    """Stateless character selection and context assembly shared by HTTP entry points."""

    def __init__(
        self,
        characters: tuple[Character, ...],
        provider: Provider,
        context: ContextSource | None = None,
        *,
        privacy: PrivacyPolicy | None = None,
    ) -> None:
        by_id = {char.config.character_id: char for char in characters}
        aliases = {char.config.alias: char for char in characters}
        if len(by_id) != len(characters) or len(aliases) != len(characters):
            raise ValueError("duplicate character id or alias")
        self.characters: Mapping[str, Character] = MappingProxyType(by_id)
        self.aliases: Mapping[str, Character] = MappingProxyType(aliases)
        self.provider = provider
        self.context = context or EmptyContext()
        self.scope = AccessScope()
        self.privacy = privacy

    async def prepare(self, selector: str, request: CompletionInput, *, alias: bool) -> Prepared:
        """Pin the character, authorize export/capabilities, and bound injected context.

        Context lookup receives server-trusted scope only after export is allowed.
        A fresh payload keeps concurrent characters and caller histories isolated.
        """
        character = (self.aliases if alias else self.characters).get(selector)
        if character is None:
            raise CoreError(404, "character_not_found", "Unknown character or model alias")
        profile = character.config.profile
        if not profile.external_send_allowed:
            raise CoreError(403, "external_send_denied", "Character export policy denies inference")
        payload = request.model_dump(exclude_none=True, exclude={"model", "character_id"})
        if "max_tokens" in payload:
            payload["max_completion_tokens"] = payload.pop("max_tokens")
        required = set(payload) - {"messages"}
        if not request.stream:
            required.discard("stream")
        if any(message.tool_calls or message.role == "tool" for message in request.messages):
            required.add("tools")
        if required - profile.allowed_parameters:
            raise CoreError(400, "unsupported_parameter", "Parameter capability is not confirmed")
        binding = Binding(self.scope, character.config.character_id)
        privacy = self.privacy
        if privacy is not None and not await privacy.authorize(
            binding, destination(profile), payload
        ):
            raise CoreError(403, "privacy_denied", "Privacy policy denies inference")
        if privacy is not self.privacy:
            raise CoreError(403, "privacy_denied", "Privacy policy changed during inference")
        user_text = next(
            (msg.content or "" for msg in reversed(request.messages) if msg.role == "user"), ""
        )
        extra = await self.context.context(character, binding.scope, user_text)
        prompt = "\n\n".join(
            part
            for part in (
                character.system_prompt,
                *(item.content for item in character.lore if item.matches(user_text)),
                extra,
            )
            if part
        )
        if len(prompt.encode("utf-8")) > character.config.context_budget_bytes:
            raise CoreError(400, "context_budget_exceeded", "Injected context exceeds byte budget")
        payload["messages"] = [{"role": "system", "content": prompt}, *payload["messages"]]
        if privacy is not self.privacy or (
            privacy is not None
            and not await privacy.authorize(binding, destination(profile), payload)
        ):
            raise CoreError(403, "privacy_denied", "Privacy policy denies inference")
        if privacy is not self.privacy:
            raise CoreError(403, "privacy_denied", "Privacy policy changed during inference")
        return Prepared(character, payload)
