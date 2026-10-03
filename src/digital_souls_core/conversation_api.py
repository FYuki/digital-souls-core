"""Explicit, opt-in conversation HTTP routes with server-owned scope."""

import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response

from .conversations import Conversations
from .history import ConversationControls, Receipt, Snapshot, TurnInput


def snapshot_body(snapshot: Snapshot) -> dict[str, Any]:
    return {
        "conversation_id": snapshot.conversation_id,
        "revision": snapshot.revision,
        "private_mode": snapshot.private_mode,
        "archived": snapshot.archived,
        "memory_sources": [
            {
                "turn_revision": state.reference.turn_revision,
                "message_index": state.reference.message_index,
                "eligible": state.eligible,
            }
            for state in snapshot.memory_sources
        ],
        "messages": [m.model_dump(exclude_none=True) for m in snapshot.messages],
    }


def register_conversations(
    app: FastAPI,
    service: Conversations,
    run: Callable[[str, str, TurnInput, Request], Awaitable[Receipt]],
) -> None:
    path = "/v1/characters/{character_id}/conversations"

    @app.post(path, status_code=201)
    async def create(character_id: str) -> dict[str, Any]:
        return snapshot_body(service.create(character_id))

    @app.get(path)
    async def list_conversations(
        character_id: str, include_archived: bool = False
    ) -> dict[str, Any]:
        return {"conversation_ids": service.list(character_id, include_archived=include_archived)}

    @app.get(path + "/{conversation_id}")
    async def read(character_id: str, conversation_id: str) -> dict[str, Any]:
        return snapshot_body(service.read(character_id, conversation_id))

    @app.patch(path + "/{conversation_id}")
    async def controls(
        character_id: str, conversation_id: str, body: ConversationControls
    ) -> dict[str, Any]:
        return snapshot_body(service.controls(character_id, conversation_id, body))

    @app.delete(path + "/{conversation_id}", status_code=204)
    async def delete(character_id: str, conversation_id: str) -> Response:
        service.delete(character_id, conversation_id)
        return Response(status_code=204)

    @app.post(path + "/{conversation_id}/completions", response_model=None)
    async def complete(
        character_id: str, conversation_id: str, body: TurnInput, request: Request
    ) -> Any:
        receipt = await run(character_id, conversation_id, body, request)
        data = {
            "conversation_id": conversation_id,
            "request_id": body.request_id,
            "revision": receipt.revision,
            "message": receipt.message.model_dump(exclude_none=True),
            "finish_reason": receipt.finish_reason,
        }
        if not body.stream:
            return data
        return Response(
            "event: completed\ndata: "
            + json.dumps(data, ensure_ascii=False)
            + "\n\ndata: [DONE]\n\n",
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache"},
        )
