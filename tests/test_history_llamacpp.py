import pytest

from digital_souls_core.conversations import request_fingerprint

from .conversation_support import turn
from .test_llamacpp_provider import local_character

pytestmark = pytest.mark.it1


def test_local_endpoint_is_part_of_retry_identity() -> None:
    config = local_character().config
    other = config.model_copy(
        update={
            "profile": config.profile.model_copy(update={"api_base": "http://127.0.0.1:18082/v1"})
        }
    )
    assert request_fingerprint(turn(), config) != request_fingerprint(turn(), other)
