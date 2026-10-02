"""Local HTTP fixture for external-client integration; never a real LLM.

Run from the checkout: uvicorn tests.fixture_server:create_fixture_app --factory
--host 127.0.0.1 --port 18080 --no-access-log
Supply a zero-argument function named fixture_ping for one tool round trip.
"""

from typing import Any

from fastapi import FastAPI

from digital_souls_core.api import create_app
from digital_souls_core.application import Inference
from digital_souls_core.character import Profile

from .support import FakeProvider, character, completion


class IntegrationFixture(FakeProvider):
    async def complete(self, profile: Profile, payload: dict[str, Any]) -> dict[str, Any]:
        response = completion(profile.model)
        if payload["messages"][-1]["role"] == "tool":
            response["choices"][0]["message"]["content"] = "fixture tool result received"
        elif any(tool["function"]["name"] == "fixture_ping" for tool in payload.get("tools", [])):
            response["choices"][0] = {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "fixture_call_1",
                            "type": "function",
                            "function": {"name": "fixture_ping", "arguments": "{}"},
                        }
                    ],
                },
            }
        return response


def create_fixture_app() -> FastAPI:
    return create_app(Inference((character(), character("other")), IntegrationFixture()))
