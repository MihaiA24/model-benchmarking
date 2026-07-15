from __future__ import annotations

import pytest

from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    ScenarioIdentity,
    ScoreContractIdentity,
    TypedDigest,
    VerifierIdentity,
)


EXPECTED_PAYLOAD_SHA256 = (
    "015abd7f5cc57a2dd94b7590f04ad8084273905ee33ec5cebeae62276a97f862"
)


def test_typed_digest_has_frozen_text_form_and_known_vector() -> None:
    digest = TypedDigest.from_bytes(DigestKind.SCENARIO, b'{"a":1}')

    assert digest.value == EXPECTED_PAYLOAD_SHA256
    assert str(digest) == f"scenario:sha256:{EXPECTED_PAYLOAD_SHA256}"
    assert TypedDigest.parse(str(digest)) == digest


def test_scenario_verifier_and_score_contract_identities_remain_independent() -> None:
    payload = {"a": 1}

    scenario = ScenarioIdentity.from_payload("1.2.3", payload)
    verifier = VerifierIdentity.from_payload("1.2.3", payload)
    score_contract = ScoreContractIdentity.from_payload("1.2.3", payload)

    assert type(scenario) is ScenarioIdentity
    assert type(verifier) is VerifierIdentity
    assert type(score_contract) is ScoreContractIdentity
    assert scenario.digest.kind is DigestKind.SCENARIO
    assert verifier.digest.kind is DigestKind.VERIFIER
    assert score_contract.digest.kind is DigestKind.SCORE_CONTRACT
    assert len({str(scenario.digest), str(verifier.digest), str(score_contract.digest)}) == 3


def test_functional_v1_identity_kinds_are_independent_and_frozen() -> None:
    kinds = (
        DigestKind.FUNCTIONAL_V1_MANIFEST,
        DigestKind.RESOLVED_V1_MANIFEST,
        DigestKind.FUNCTIONAL_V1_CONDITION,
        DigestKind.RESULT_BUNDLE,
        DigestKind.FUNCTIONAL_V1_RUN_RECORD,
    )

    identities = [TypedDigest.from_bytes(kind, b"same canonical bytes") for kind in kinds]

    assert [identity.kind.value for identity in identities] == [
        "functional-v1-manifest",
        "resolved-v1-manifest",
        "functional-v1-condition",
        "result-bundle",
        "functional-v1-run-record",
    ]
    assert len({str(identity) for identity in identities}) == len(kinds)
    assert all(TypedDigest.parse(str(identity)) == identity for identity in identities)


@pytest.mark.parametrize(
    "value",
    [
        "scenario:sha1:" + "0" * 64,
        "unknown:sha256:" + "0" * 64,
        "scenario:sha256:" + "A" * 64,
        "scenario:sha256:short",
    ],
)
def test_typed_digest_rejects_unknown_or_malformed_values(value: str) -> None:
    with pytest.raises(IdentityError):
        TypedDigest.parse(value)


@pytest.mark.parametrize("version", ["1", "v1.0.0", "01.0.0", "1.0"])
def test_versioned_identity_requires_strict_semver(version: str) -> None:
    with pytest.raises(IdentityError):
        ScenarioIdentity.from_payload(version, {"a": 1})
