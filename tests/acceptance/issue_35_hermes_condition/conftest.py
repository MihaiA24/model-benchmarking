from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest


@pytest.fixture
def recording_provider(
    recording_provider_factory: Callable[..., Any],
) -> Iterator[Any]:
    # The shared provider double lives in tests/conftest.py so it stays
    # inside every proof's sealed source closure; the canned reply is the
    # stock chat-completion usage record, while each trial enqueues its
    # /api/show capability exchange ahead of it.
    with recording_provider_factory(
        base_path="",
        default_json={
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                    "index": 0,
                }
            ],
            "created": 1,
            "id": "chatcmpl-functional-v1",
            "model": "locked/model",
            "object": "chat.completion.chunk",
            "usage": {
                "completion_tokens": 5,
                "cost_usd": "0.10",
                "prompt_tokens": 12,
                "total_tokens": 17,
            },
        },
        default_cost_header="0.10",
    ) as provider:
        yield provider
