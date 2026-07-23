from __future__ import annotations

from pathlib import Path

from model_benchmark.declarations.functional_v1 import (
    CONDITIONS,
    SCENARIOS,
    FunctionalV1Manifest,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = _REPOSITORY_ROOT / "functional-v1-hy3.yaml"


def test_published_hy3_manifest_loads_with_sealed_projection() -> None:
    manifest = FunctionalV1Manifest.load(_MANIFEST_PATH)

    assert str(manifest.identity) == (
        "functional-v1-manifest:sha256:"
        "1e09033e989960d4232f09662d5f9902df3beb0e84c0333f85a081e692814a63"
    )
    assert str(manifest.resolved_identity) == (
        "resolved-v1-manifest:sha256:"
        "df3dddfa82180432e31d06febdef1138683f3e7aa156d0cf0789f8a51bde1b0c"
    )
    assert manifest.identity_value["provider"] == {
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "hy3",
        "pricing": {
            "schema_version": 1,
            "currency": "USD",
            "unit": "usd-per-million-tokens",
            "input_usd_per_million_tokens": "0.14",
            "output_usd_per_million_tokens": "0.58",
            "effective_from_utc": "2026-07-22T00:00:00Z",
            "effective_until_utc": "2026-09-01T00:00:00Z",
            "source_url": "https://models.dev/providers/opencode-go",
            "retrieved_at_utc": "2026-07-22T23:01:53Z",
            "identity": (
                "pricing-record:sha256:"
                "839345de1c365754df4745dcffec03b98a3102723bfe4926273401478557afea"
            ),
        },
    }
    assert tuple(manifest.identity_value["scenarios"]) == SCENARIOS
    assert tuple(manifest.identity_value["conditions"]) == CONDITIONS
    assert len(SCENARIOS) * len(CONDITIONS) == 16
    assert manifest.identity_value["limits"] == {
        "requests_per_trial": 64,
        "provider_tokens_per_trial": 375_000,
        "stop_after_cost_usd_per_trial": "5.00",
        "wall_time_seconds_per_trial": 1_800,
        "cpu_cores_per_trial": 2,
        "memory_mib_per_trial": 4_096,
        "writable_disk_mib_per_trial": 8_192,
    }
    assert manifest.identity_value["execution"] == {
        "max_parallel": 3,
        "network_policy": "proxy-only-v1",
    }
