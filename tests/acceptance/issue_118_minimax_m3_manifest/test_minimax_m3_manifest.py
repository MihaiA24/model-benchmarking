from __future__ import annotations

from pathlib import Path

from model_benchmark.declarations.functional_v1 import (
    CONDITIONS,
    SCENARIOS,
    FunctionalV1Manifest,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_MANIFEST_PATH = _REPOSITORY_ROOT / "functional-v1-minimax-m3.yaml"


def test_published_minimax_m3_manifest_loads_with_sealed_projection() -> None:
    manifest = FunctionalV1Manifest.load(_MANIFEST_PATH)

    assert str(manifest.identity) == (
        "functional-v1-manifest:sha256:"
        "c521dc9e5292b8174f2af000398ef27ed8b9158a066ac7a1a7c692555d0da0a8"
    )
    assert str(manifest.resolved_identity) == (
        "resolved-v1-manifest:sha256:"
        "c7462919acc6e1cc242d3dd089fe081663feb19912992e234aff1f64b8e01589"
    )
    assert manifest.identity_value["provider"] == {
        "base_url": "https://opencode.ai/zen/go/v1",
        "protocol": "anthropic-messages",
        "model": "minimax-m3",
        "pricing": {
            "schema_version": 3,
            "billing_basis": "opencode-go-catalog",
            "currency": "USD",
            "unit": "usd-per-million-tokens",
            "input_usd_per_million_tokens": "0.30",
            "output_usd_per_million_tokens": "1.20",
            "cache_read_usd_per_million_tokens": "0.06",
            "tiers": [
                {
                    "input_tokens_gt": 512_000,
                    "input_usd_per_million_tokens": "0.60",
                    "output_usd_per_million_tokens": "2.40",
                    "cache_read_usd_per_million_tokens": "0.12",
                }
            ],
            "effective_from_utc": "2026-07-22T00:00:00Z",
            "effective_until_utc": "2026-09-01T00:00:00Z",
            "source_url": "https://models.dev/api.json",
            "source_snapshot_sha256": (
                "sha256:"
                "0fde178efd91764a20ae11948d9c26cdaad216a76efcd48590904962b77bb48e"
            ),
            "retrieved_at_utc": "2026-07-23T07:08:24Z",
            "identity": (
                "pricing-record:sha256:"
                "74f5cec73deffbe44e4a6b5ead7c742dd47b73df05cbc7a7ce8ba9e1f179f8b9"
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
