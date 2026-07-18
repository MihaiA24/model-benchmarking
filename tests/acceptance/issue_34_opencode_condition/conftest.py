from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

import pytest


_CANNED_COMPLETION = {
    "choices": [
        {
            "delta": {"content": "done", "role": "assistant"},
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
}


@pytest.fixture
def recording_provider(
    recording_provider_factory: Callable[..., Any],
) -> Iterator[Any]:
    with recording_provider_factory(
        base_path="",
        default_json=_CANNED_COMPLETION,
        default_cost_header="0.10",
    ) as provider:
        yield provider
