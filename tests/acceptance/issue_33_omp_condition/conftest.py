from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest


@pytest.fixture
def recording_provider(
    recording_provider_factory: Callable[..., Any],
) -> Iterator[Any]:
    # The shared provider double lives in tests/conftest.py so it stays
    # inside every proof's sealed source closure; this suite speaks the
    # canned-completion dialect against the API root.
    provider = recording_provider_factory(
        base_path="",
        default_json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "index": 0,
                    "message": {"content": "done", "role": "assistant"},
                }
            ],
            "model": "locked/model",
            "usage": {
                "completion_tokens": 5,
                "cost_usd": "0.10",
                "prompt_tokens": 12,
                "total_tokens": 17,
            },
        },
        default_cost_header="0.10",
    )
    with provider:
        yield provider
