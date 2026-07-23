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
        "ef8f10a78c0c5e9e2e977883bd00e97c826d174d79b20fe54f612d7ef91026a2"
    )
    assert str(manifest.resolved_identity) == (
        "resolved-v1-manifest:sha256:"
        "88ba11e5b3c1b95fc14b9f1760739cc493921b0b865500af840acf23323319bb"
    )
    assert manifest.identity_value["provider"] == {
        "base_url": "https://opencode.ai/zen/go/v1",
        "protocol": "openai-chat-completions",
        "model": "hy3",
        "pricing": {
            "schema_version": 3,
            "billing_basis": "opencode-go-catalog",
            "currency": "USD",
            "unit": "usd-per-million-tokens",
            "input_usd_per_million_tokens": "0.14",
            "output_usd_per_million_tokens": "0.58",
            "cache_read_usd_per_million_tokens": "0.035",
            "tiers": [],
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
                "97498b9f6d24dc58be4dd62a54d56c8d94add242cb59c3088a322b7b49df7044"
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
