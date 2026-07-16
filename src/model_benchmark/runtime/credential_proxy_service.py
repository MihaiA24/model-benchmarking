from __future__ import annotations

import os
import signal
import threading
from decimal import Decimal
from pathlib import Path

from model_benchmark.declarations.limits import FIXED_LIMITS
from model_benchmark.runtime.credential_proxy import (
    PROVIDER_API_KEY_ENV,
    TRIAL_PROXY_TOKEN_ENV,
    CredentialProxy,
    CredentialProxyConfig,
)


def main() -> int:
    stop = threading.Event()
    for selected in (signal.SIGINT, signal.SIGTERM):
        signal.signal(selected, lambda _signum, _frame: stop.set())

    config = CredentialProxyConfig(
        upstream_base_url=os.environ["MODEL_BENCHMARK_PROVIDER_BASE_URL"],
        model=os.environ["MODEL_BENCHMARK_PROVIDER_MODEL"],
        requests_per_trial=FIXED_LIMITS["requests_per_trial"],
        provider_tokens_per_trial=int(
            os.environ["MODEL_BENCHMARK_PROVIDER_TOKENS_PER_TRIAL"]
        ),
        stop_after_cost_usd_per_trial=Decimal(
            os.environ["MODEL_BENCHMARK_STOP_AFTER_COST_USD_PER_TRIAL"]
        ),
        evidence_path=Path("/evidence/proxy.jsonl"),
        listen_host="0.0.0.0",
        listen_port=8080,
        real_api_key=os.environ[PROVIDER_API_KEY_ENV],
        trial_token=os.environ[TRIAL_PROXY_TOKEN_ENV],
    )
    with CredentialProxy(config):
        stop.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
