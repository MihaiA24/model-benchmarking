from __future__ import annotations

import json
import os
import signal
import threading
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit

from model_benchmark.declarations.provider_routes import (
    PROVIDER_PROTOCOL_ENV,
    parse_provider_protocol,
    provider_protocol_spec,
)

from model_benchmark.runtime.credential_proxy import (
    PROVIDER_API_KEY_ENV,
    PRICING_TIERS_ENV,
    TRIAL_PROXY_TOKEN_ENV,
    CredentialProxy,
    CredentialProxyConfig,
    PricingRecord,
    PricingTier,
)
from model_benchmark.runtime.dry_launch_provider import (
    DRY_LAUNCH_API_KEY,
    DRY_LAUNCH_ENV,
    DryLaunchProvider,
)

_TIER_FIELDS = frozenset(
    {
        "cache_read_usd_per_million_tokens",
        "input_tokens_gt",
        "input_usd_per_million_tokens",
        "output_usd_per_million_tokens",
    }
)


def _pricing_tier(record: object) -> PricingTier:
    if not isinstance(record, dict) or set(record) != _TIER_FIELDS:
        raise ValueError("sealed pricing tier is malformed")
    threshold = record["input_tokens_gt"]
    rates = (
        record["input_usd_per_million_tokens"],
        record["output_usd_per_million_tokens"],
        record["cache_read_usd_per_million_tokens"],
    )
    if (
        not isinstance(threshold, int)
        or isinstance(threshold, bool)
        or any(not isinstance(rate, str) for rate in rates)
    ):
        raise ValueError("sealed pricing tier fields are invalid")
    try:
        input_rate, output_rate, cache_read_rate = map(Decimal, rates)
    except InvalidOperation as error:
        raise ValueError("sealed pricing tier rates are invalid") from error
    return PricingTier(
        input_tokens_gt=threshold,
        input_usd_per_million_tokens=input_rate,
        output_usd_per_million_tokens=output_rate,
        cache_read_usd_per_million_tokens=cache_read_rate,
    )


def _pricing_tiers() -> tuple[PricingTier, ...]:
    try:
        value = json.loads(os.environ[PRICING_TIERS_ENV])
    except (KeyError, json.JSONDecodeError) as error:
        raise ValueError("sealed pricing tiers are absent or invalid") from error
    if not isinstance(value, list):
        raise ValueError("sealed pricing tiers must be a JSON array")
    return tuple(_pricing_tier(record) for record in value)


def _serve(stop: threading.Event, *, upstream_base_url: str, real_api_key: str) -> int:
    protocol = parse_provider_protocol(os.environ[PROVIDER_PROTOCOL_ENV])
    protocol_spec = provider_protocol_spec(protocol)
    config = CredentialProxyConfig(
        upstream_base_url=upstream_base_url,
        model=os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
        provider_protocol=protocol,
        requests_per_trial=int(os.environ["MODEL_BENCHMARK_REQUESTS_PER_TRIAL"]),
        provider_tokens_per_trial=int(
            os.environ["MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL"]
        ),
        stop_after_cost_usd_per_trial=Decimal(
            os.environ["MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL"]
        ),
        evidence_path=Path("/evidence/proxy.jsonl"),
        pricing_record=PricingRecord(
            identity=os.environ["MODEL_BENCHMARK_PRICING_RECORD_IDENTITY"],
            input_usd_per_million_tokens=Decimal(
                os.environ["MODEL_BENCHMARK_INPUT_USD_PER_MILLION_TOKENS"]
            ),
            output_usd_per_million_tokens=Decimal(
                os.environ["MODEL_BENCHMARK_OUTPUT_USD_PER_MILLION_TOKENS"]
            ),
            cache_read_usd_per_million_tokens=Decimal(
                os.environ["MODEL_BENCHMARK_CACHE_READ_USD_PER_MILLION_TOKENS"]
            ),
            tiers=_pricing_tiers(),
        ),
        listen_host="0.0.0.0",
        listen_port=8080,
        allowed_endpoint_paths=(protocol_spec.endpoint_path,),
        real_api_key=real_api_key,
        trial_token=os.environ[TRIAL_PROXY_TOKEN_ENV],
    )
    with CredentialProxy(config):
        stop.wait()
    return 0


def main() -> int:
    stop = threading.Event()
    for selected in (signal.SIGINT, signal.SIGTERM):
        signal.signal(selected, lambda _signum, _frame: stop.set())

    dry_launch = os.environ.get(DRY_LAUNCH_ENV)
    if dry_launch not in {None, "1"}:
        raise ValueError(f"{DRY_LAUNCH_ENV} must be absent or 1")
    upstream_base_url = os.environ["MODEL_BENCHMARK_PROVIDER_BASE_URL"]
    if dry_launch is None:
        return _serve(
            stop,
            upstream_base_url=upstream_base_url,
            real_api_key=os.environ[PROVIDER_API_KEY_ENV],
        )

    parsed = urlsplit(upstream_base_url)
    with DryLaunchProvider(
        model=os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
        protocol=parse_provider_protocol(os.environ[PROVIDER_PROTOCOL_ENV]),
        route_prefix=parsed.path,
    ) as provider:
        return _serve(
            stop,
            upstream_base_url=provider.base_url,
            real_api_key=DRY_LAUNCH_API_KEY,
        )


if __name__ == "__main__":
    raise SystemExit(main())
