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
    # exact-sequence dialect against the /v1 API root.
    with recording_provider_factory(base_path="/v1") as provider:
        yield provider
