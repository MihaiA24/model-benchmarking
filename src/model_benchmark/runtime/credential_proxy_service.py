from __future__ import annotations

import os
import signal
import threading
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from model_benchmark.runtime.credential_proxy import (
    PROVIDER_API_KEY_ENV,
    TRIAL_PROXY_TOKEN_ENV,
    CredentialProxy,
    CredentialProxyConfig,
    PricingRecord,
)
from model_benchmark.runtime.dry_launch_provider import (
    DRY_LAUNCH_API_KEY,
    DRY_LAUNCH_ENV,
    DryLaunchProvider,
)


def _serve(stop: threading.Event, *, upstream_base_url: str, real_api_key: str) -> int:
    config = CredentialProxyConfig(
        upstream_base_url=upstream_base_url,
        model=os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
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
        ),
        listen_host="0.0.0.0",
        listen_port=8080,
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
        route_prefix=parsed.path,
    ) as provider:
        return _serve(
            stop,
            upstream_base_url=provider.base_url,
            real_api_key=DRY_LAUNCH_API_KEY,
        )


if __name__ == "__main__":
    raise SystemExit(main())
