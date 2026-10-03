import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from digital_souls_core.api import create_app
from digital_souls_core.application import CoreError
from digital_souls_core.privacy_scan import scan

from .support import CALL, TOOL, chunk, completion
from .test_conversations import turn
from .test_privacy import BINDING, policy_setup

pytestmark = pytest.mark.it1


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "090 1234 5678", 4111111111111111])
@pytest.mark.parametrize("shape", ["payload", "nested", "encoded", "siblings"])
def test_numeric_field_boundaries(number: str | int, shape: str) -> None:
    value: object = {"messages": [{"role": "user", "content": number}]}
    if shape == "nested":
        value = {"outer": [{"value": number}, {"other": "123456789"}]}
    elif shape == "encoded":
        value = {"arguments": json.dumps({"number": number, "other": "123456789"})}
    elif shape == "siblings":
        value = {"first": number, "second": number}
    assert scan(value).secret and not scan(value).failed


@pytest.mark.parametrize(
    "value",
    [
        {"first": "41111111", "second": "11111111"},
        ["090", "1234", "5678"],
        {"first": 41111111, "second": 11111111},
    ],
)
def test_unrelated_fields_do_not_form_identifiers(value: object) -> None:
    assert not scan(value).secret and not scan(value).failed


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "090 1234 5678"])
@pytest.mark.parametrize("local", [False, True])
def test_http_numeric_input_blocks_provider_and_database(
    tmp_path: Path, number: str, local: bool
) -> None:
    service, provider, classifier, policy = policy_setup(tmp_path, local=local)
    cid = service.create("synthetic").conversation_id
    http = TestClient(
        create_app(service.inference, history_store=service.store, history_policy=policy),
        base_url="http://127.0.0.1",
    )
    body = turn(messages=[{"role": "user", "content": number}]).model_dump()
    response = http.post(f"/v1/characters/synthetic/conversations/{cid}/completions", json=body)
    assert response.status_code == 403
    assert provider.calls == [] and classifier.calls == []
    assert service.read("synthetic", cid).messages == ()
    assert service.store.receipt(BINDING, cid, "r1") is None
    for file in (tmp_path / "private").iterdir():
        assert number.encode() not in file.read_bytes()


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "090 1234 5678"])
@pytest.mark.parametrize("where", ["assistant", "stream", "tool_args", "tool_result", "schema"])
async def test_numeric_history_boundaries(tmp_path: Path, number: str, where: str) -> None:
    service, provider, classifier, _ = policy_setup(tmp_path, local=False)
    cid = service.create("synthetic").conversation_id
    body = turn()
    if where == "assistant":
        provider.response["choices"][0]["message"]["content"] = number
    elif where == "stream":
        provider.chunks = [chunk({"content": part}) for part in number] + [chunk({}, "stop")]
        body = turn(stream=True)
    elif where == "tool_args":
        provider.response = completion(tool=True)
        provider.response["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
            json.dumps({"value": number})
        )
        body = turn(tools=[TOOL])
    elif where == "tool_result":
        provider.response = completion(tool=True)
        await service.complete("synthetic", cid, turn(tools=[TOOL]))
        provider.calls.clear()
        classifier.calls.clear()
        body = turn(
            request_id="r2",
            expected_revision=1,
            tools=[TOOL],
            messages=[
                {
                    "role": "tool",
                    "tool_call_id": CALL["id"],
                    "content": json.dumps({"value": number}),
                }
            ],
        )
    else:
        tool = json.loads(json.dumps(TOOL))
        tool["function"]["description"] = number
        body = turn(tools=[tool])
    before = service.read("synthetic", cid)
    with pytest.raises(CoreError):
        await service.complete("synthetic", cid, body)
    assert service.read("synthetic", cid) == before
    assert service.store.receipt(BINDING, cid, body.request_id) is None
    assert all(number not in json.dumps(payload) for _, payload in classifier.calls)
    if where in {"tool_result", "schema"}:
        assert provider.calls == []
    for file in (tmp_path / "private").iterdir():
        assert number.encode() not in file.read_bytes()


@pytest.mark.parametrize("value", [True, False, None, [True, False, None], {"enum": [1, 2, 3]}])
def test_boolean_null_and_short_numbers_are_not_identifiers(value: object) -> None:
    assert not scan(value).secret and not scan(value).failed


@pytest.mark.parametrize(
    "value",
    [
        r'{"\u0070assword":"synthetic-value","\u0070assword":""}',
        r'{"value":"\u0073k-proj-syntheticsyntheticsynthetic","value":"safe"}',
        "[" * 1500 + '"password: synthetic"' + "]" * 1500,
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":',
        "9" * 5000,
    ],
)
def test_ambiguous_or_unbounded_json_fails_closed(value: str) -> None:
    assert scan({"arguments": value}).failed


@pytest.mark.parametrize(
    "value",
    [
        r'{"\u0070assword":"synthetic-value","\u0070assword":""}',
        "[" * 1500 + '"password: synthetic"' + "]" * 1500,
    ],
)
async def test_encoded_json_rejected_before_classifier_and_provider(
    tmp_path: Path, value: str
) -> None:
    service, provider, classifier, _ = policy_setup(tmp_path, local=False)
    cid = service.create("synthetic").conversation_id
    with pytest.raises(CoreError):
        await service.complete(
            "synthetic", cid, turn(messages=[{"role": "user", "content": value}])
        )
    assert provider.calls == [] and classifier.calls == []
    assert service.read("synthetic", cid).messages == ()
    assert service.store.receipt(BINDING, cid, "r1") is None


@pytest.mark.parametrize("number", [4111111111111111, 4111111111111111.0, 4.111111111111111e15])
async def test_numeric_tool_enum_rejected_before_send(tmp_path: Path, number: int | float) -> None:
    service, provider, classifier, _ = policy_setup(tmp_path, local=False)
    cid = service.create("synthetic").conversation_id
    tool = json.loads(json.dumps(TOOL))
    tool["function"]["parameters"]["properties"]["city"]["enum"] = [number]
    with pytest.raises(CoreError):
        await service.complete("synthetic", cid, turn(tools=[tool]))
    assert provider.calls == [] and classifier.calls == []
    assert service.read("synthetic", cid).messages == ()


@pytest.mark.parametrize(
    "key",
    [
        "api key",
        "access-token",
        "private-key",
        "recovery code",
        "seed phrase",
        "my password",
        "shipping address",
        "api_key",
    ],
)
@pytest.mark.parametrize("encoded", [False, True])
def test_structured_label_variants_preserve_detection(key: str, encoded: bool) -> None:
    payload = {"nested": {key: "SYNTHETIC_OPAQUE_VALUE"}}
    value: object = {"arguments": json.dumps(payload)} if encoded else payload
    assert scan(value).secret


@pytest.mark.parametrize(
    "token",
    [
        "4111111111111111.0",
        "4.111111111111111e15",
        "411111111111111100e-2",
        "4111111111111111.25",
        "411111111111111100000000000000000000e-20",
    ],
)
@pytest.mark.parametrize("shape", ["scalar", "enum", "arguments"])
def test_decimal_json_preserves_identifier_digits(token: str, shape: str) -> None:
    value: object = token
    if shape == "enum":
        value = '{"enum":[' + token + "]}"
    elif shape == "arguments":
        value = {"arguments": '{"value":' + token + "}"}
    finding = scan(value)
    assert finding.secret and not finding.failed


@pytest.mark.parametrize(
    "value",
    [
        4111111111111111.0,
        4111111111111111111.0,
        1e13,
        1e100,
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
        "-Infinity",
        "1e309",
        '{"value":1e309}',
        '{"value":-1e309}',
        "1e10000",
        "1e-10000",
        '{"enum":[NaN]}',
        '{"enum":[1e10000]}',
    ],
)
def test_unsupported_numeric_forms_fail_closed(value: object) -> None:
    assert scan({"value": value}).failed


@pytest.mark.parametrize(
    "value",
    [
        1.8e-13,
        {"tolerance": 1.8e-13},
        "0e-13",
        "0.0000000000000",
        '{"tolerance": 0.0000000000000}',
        '{"tolerance": 1.8e-13}',
        0.0,
        -0.0,
        0.25,
        -12.5,
        42.0,
        1e-6,
        1e6,
        "0.25",
        "-12.5",
        "4.2e1",
        "1e-6",
        "1e6",
        {"enum": [0.25, 42.0]},
        '{"enum":[0.25,4.2e1]}',
    ],
)
def test_ordinary_float_values_are_not_secrets(value: object) -> None:
    finding = scan(value)
    assert not finding.secret and not finding.failed


@pytest.mark.parametrize("token", ["4.111111111111111e15", "4111111111111111.0"])
async def test_decimal_encoded_value_blocked_before_send(tmp_path: Path, token: str) -> None:
    service, provider, classifier, _ = policy_setup(tmp_path, local=False)
    cid = service.create("synthetic").conversation_id
    with pytest.raises(CoreError):
        await service.complete(
            "synthetic",
            cid,
            turn(
                messages=[
                    {"role": "user", "content": '{"enum":[' + token + "]}"},
                ]
            ),
        )
    assert provider.calls == [] and classifier.calls == []
    assert service.read("synthetic", cid).messages == ()
