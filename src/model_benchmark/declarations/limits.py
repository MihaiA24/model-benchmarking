"""Fixed Functional V1 per-Trial resource envelope.

The credential-proxy image is a bare Python base plus the copied
``model_benchmark`` tree — no third-party distributions exist inside it.
This module is imported by that sealed runtime, so it and its import
closure must stay standard-library only
(guarded by ``tests/architecture/test_import_boundaries.py``).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType


FIXED_LIMITS: Mapping[str, int] = MappingProxyType(
    {
        "requests_per_trial": 64,
        "wall_time_seconds_per_trial": 1_800,
        "cpu_cores_per_trial": 2,
        "memory_mib_per_trial": 4_096,
        "writable_disk_mib_per_trial": 8_192,
    }
)
