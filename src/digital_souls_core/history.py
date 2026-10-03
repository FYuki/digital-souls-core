"""Storage-independent conversation contracts and trusted authorization boundary."""

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from pydantic import Field

from .character import AccessScope
from .contracts import Message, Name, NamedToolChoice, StrictModel, Tool


class TurnInput(StrictModel):
    request_id: Name
    expected_revision: Annotated[int, Field(ge=0)]
    messages: Annotated[list[Message], Field(min_length=1, max_length=128)]
    stream: bool = False
    tools: Annotated[list[Tool], Field(min_length=1, max_length=128)] | None = None
    tool_choice: Literal["auto", "none", "required"] | NamedToolChoice | None = None
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] | None = None
    max_tokens: Annotated[int, Field(gt=0, le=32768)] | None = None
    max_completion_tokens: Annotated[int, Field(gt=0, le=32768)] | None = None


@dataclass(frozen=True)
class Binding:
    scope: AccessScope
    character_id: str


@dataclass(frozen=True)
class Snapshot:
    conversation_id: str
    revision: int
    messages: tuple[Message, ...]


@dataclass(frozen=True)
class Receipt:
    fingerprint: str
    revision: int
    message: Message
    finish_reason: str


type Operation = Literal["create", "list", "read", "export", "store"]


class HistoryPolicy(Protocol):
    """Operator-injected stage-2 seam; absent/uncertain policy must deny.

    Checks include secrets in tool arguments/results as well as visible text.
    HTTP callers cannot install this policy or assert that input is safe.
    Deletion is authorized by binding alone so revoked consent cannot trap data.
    """

    def allows(
        self, operation: Operation, binding: Binding, messages: tuple[Message, ...]
    ) -> bool: ...


class HistoryStore(Protocol):
    def create(self, binding: Binding) -> Snapshot: ...
    def list(self, binding: Binding) -> list[str]: ...
    def read(self, binding: Binding, conversation_id: str) -> Snapshot: ...
    def receipt(
        self, binding: Binding, conversation_id: str, request_id: str
    ) -> Receipt | None: ...
    def append(
        self,
        binding: Binding,
        conversation_id: str,
        request_id: str,
        fingerprint: str,
        expected_revision: int,
        messages: tuple[Message, ...],
        finish_reason: str,
    ) -> Receipt: ...
    def delete(self, binding: Binding, conversation_id: str) -> None: ...
