"""LiteLLM adapter: transport only, with no tool execution or routing fallback."""

import inspect
import os
from collections.abc import AsyncGenerator
from typing import Any

import anyio

from .application import CoreError
from .character import Profile

# Keep SDK import-time metadata access offline. No credentials are copied or logged.
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

import litellm as litellm  # noqa: E402

litellm.suppress_debug_info = True
litellm.set_verbose = False
litellm.turn_off_message_logging = True
litellm.telemetry = False


def provider_error(error: Exception) -> CoreError:
    if isinstance(error, litellm.UnsupportedParamsError):
        return CoreError(400, "unsupported_parameter", "Provider rejected an unsupported parameter")
    if isinstance(error, litellm.Timeout):
        return CoreError(504, "provider_timeout", "Provider timed out")
    if isinstance(error, litellm.RateLimitError):
        return CoreError(429, "provider_rate_limit", "Provider rate limit reached")
    return CoreError(502, "provider_error", "Provider request failed")


class LiteLLMProvider:
    @staticmethod
    async def _call(profile: Profile, payload: dict[str, Any]) -> Any:
        if not profile.external_send_allowed:
            raise CoreError(403, "external_send_denied", "Character export policy denies inference")
        return await litellm.acompletion(
            model=profile.model,
            **payload,
            timeout=profile.timeout_seconds,
            num_retries=0,
            max_retries=0,
            drop_params=False,
            fallbacks=[],
        )

    async def complete(self, profile: Profile, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            result = await self._call(profile, payload)
            return dict(result.model_dump(exclude_none=True))
        except CoreError:
            raise
        except Exception as error:
            raise provider_error(error) from None

    async def stream(
        self, profile: Profile, payload: dict[str, Any]
    ) -> AsyncGenerator[dict[str, Any]]:
        upstream = None
        try:
            upstream = await self._call(profile, payload)
            async for chunk in upstream:
                yield chunk.model_dump(exclude_none=True)
        except CoreError:
            raise
        except Exception as error:
            raise provider_error(error) from None
        finally:
            if upstream is not None:
                # LiteLLM 1.77's wrapper exposes its underlying SDK stream.
                # OpenAI AsyncStream uses close(); async generators use aclose().
                transport = getattr(upstream, "completion_stream", upstream)
                close = getattr(transport, "aclose", None) or getattr(transport, "close", None)
                if close is not None:
                    # Starlette disconnect uses an AnyIO cancelled scope. Cleanup
                    # must survive its repeated cancellation at I/O checkpoints.
                    with anyio.CancelScope(shield=True):
                        try:
                            result = close()
                            if inspect.isawaitable(result):
                                await result
                        except Exception:
                            raise CoreError(
                                502, "provider_error", "Provider stream close failed"
                            ) from None
