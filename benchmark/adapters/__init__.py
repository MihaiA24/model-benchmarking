"""Harness adapter registry."""

from .base import AdapterResult, HarnessAdapter
from .cli import HermesAdapter, OmpAdapter, OpenCodeAdapter
from .raw_api import RawApiAdapter

ADAPTERS = {
    "raw_api": RawApiAdapter,
    "omp": OmpAdapter,
    "opencode": OpenCodeAdapter,
    "hermes": HermesAdapter,
}

AGENT_HARNESSES = ("omp", "opencode", "hermes")
ALL_HARNESSES = ("raw_api",) + AGENT_HARNESSES

__all__ = [
    "ADAPTERS",
    "AGENT_HARNESSES",
    "ALL_HARNESSES",
    "AdapterResult",
    "HarnessAdapter",
    "RawApiAdapter",
    "OmpAdapter",
    "OpenCodeAdapter",
    "HermesAdapter",
]
