import json

import pytest

from digital_souls_core import structured_output
from digital_souls_core.application import CoreError
from digital_souls_core.local_extractor import Extraction

from . import test_postgres_stores
from .postgres_memory_support import setup, source
from .privacy_support import BINDING
from .test_postgres_stores import Stores

pytestmark = pytest.mark.postgres
stores = test_postgres_stores.stores


@pytest.mark.parametrize("change", ["schema", "contract", "sdk", "legacy"])
async def test_structured_approval_change_requires_explicit_retry(
    stores: Stores, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    service, conversation, provider = setup(stores)
    ref = await source(conversation)
    versions = service._versions()
    if change == "legacy":
        legacy = json.loads(versions)
        for adapter in legacy.values():
            for key in ("structured_output_contract", "response_schema_sha256", "provider_sdk"):
                adapter.pop(key)
        versions = json.dumps(legacy, sort_keys=True)
    evidence = service.store.sources(BINDING, (ref,))
    service.store.begin(BINDING, tuple(e.source for e in evidence), versions)
    if change == "schema":
        schema = Extraction.model_json_schema()
        schema["title"] = "SyntheticNewContract"
        monkeypatch.setattr(Extraction, "model_json_schema", classmethod(lambda cls: schema))
    elif change == "contract":
        monkeypatch.setattr(structured_output, "CONTRACT_VERSION", "synthetic-contract-v2")
    elif change == "sdk":
        monkeypatch.setattr(structured_output, "version", lambda package: "synthetic-v2")
    with pytest.raises(CoreError, match="explicit extraction"):
        await service.rebuild(BINDING)
    assert provider.calls == [] and service.store.pending(BINDING) == ()
    assert service.store.search(BINDING, "tea") == ()
    assert len(await service.extract(BINDING, (ref,))) == 1
