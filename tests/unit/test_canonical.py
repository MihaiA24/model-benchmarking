from __future__ import annotations

import pytest

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    load_canonical_json,
)


def test_canonical_json_has_frozen_key_order_and_bytes() -> None:
    value = {"z": [True, None, 3], "a": {"é": "mañana", "a": "first"}}

    assert canonical_json_bytes(value) == (
        '{"a":{"a":"first","é":"mañana"},"z":[true,null,3]}'.encode("utf-8")
    )


@pytest.mark.parametrize(
    "value",
    [
        1.5,
        {"value": float("nan")},
        {"value": 2**63},
        {"value": "e\u0301"},
        {"value": {1, 2}},
    ],
)
def test_canonical_json_rejects_ambiguous_values(value: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonical_json_bytes(value)


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"z":1, "a":2}',
        b'{"number":1.0}',
    ],
)
def test_canonical_loader_rejects_duplicate_or_noncanonical_input(payload: bytes) -> None:
    with pytest.raises(CanonicalizationError):
        load_canonical_json(payload)


def test_canonical_loader_round_trips_byte_identically() -> None:
    payload = b'{"a":[1,2,3],"b":"text"}'

    assert canonical_json_bytes(load_canonical_json(payload)) == payload
