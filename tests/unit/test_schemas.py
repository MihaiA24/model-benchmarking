from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

import pytest

from model_benchmark.declarations.canonical import (
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT / "schemas"
VALID_FIXTURE = ROOT / "tests/fixtures/conformance/identity-set-v1.valid.json"


def _valid_document() -> dict[str, object]:
    value = load_canonical_json(VALID_FIXTURE.read_bytes())
    assert isinstance(value, dict)
    return value


def test_published_schemas_are_canonical_and_match_catalog_digests() -> None:
    registry = SchemaRegistry(SCHEMA_ROOT)

    canonicalization_bytes = (
        SCHEMA_ROOT / registry.canonicalization.file
    ).read_bytes()
    assert canonical_json_bytes(
        load_canonical_json(canonicalization_bytes)
    ) == canonicalization_bytes
    assert str(
        TypedDigest.from_bytes(DigestKind.CANONICALIZATION, canonicalization_bytes)
    ) == registry.canonicalization.sha256

    for entry in registry.entries:
        schema_bytes = (SCHEMA_ROOT / entry.file).read_bytes()
        assert canonical_json_bytes(load_canonical_json(schema_bytes)) == schema_bytes
        assert str(TypedDigest.from_bytes(DigestKind.SCHEMA, schema_bytes)) == entry.sha256


def test_identity_fixture_validates_with_independent_typed_identities() -> None:
    document = SchemaRegistry(SCHEMA_ROOT).validate_path(VALID_FIXTURE)

    identities = document["identities"]
    assert isinstance(identities, dict)
    assert identities["scenario"]["kind"] == "scenario"
    assert identities["verifier"]["kind"] == "verifier"
    assert identities["score_contract"]["kind"] == "score-contract"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["identities"]["scenario"].update({"kind": "unknown"}),
        lambda value: value["schema"].update({"version": 2}),
        lambda value: value["schema"].update(
            {"sha256": "schema:sha256:" + "0" * 64}
        ),
        lambda value: value["schema"].update(
            {"canonicalization_sha256": "canonicalization:sha256:" + "0" * 64}
        ),
    ],
    ids=[
        "unknown-field",
        "unknown-enum",
        "unknown-version",
        "schema-digest",
        "canonicalization-digest",
    ],
)
def test_schema_validation_fails_closed(
    mutation: Callable[[dict[str, object]], object],
) -> None:
    document = deepcopy(_valid_document())
    mutation(document)

    with pytest.raises(SchemaValidationError):
        SchemaRegistry(SCHEMA_ROOT).validate_bytes(canonical_json_bytes(document))
