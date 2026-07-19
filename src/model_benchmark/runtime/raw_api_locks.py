"""Host-side lock plumbing for the Raw API condition.

Kept out of ``raw_api.py`` on purpose: that module is imported inside the
sealed condition image (``condition_image`` → ``raw_api_launch`` →
``raw_api``), where only the standard library and the copied
``model_benchmark`` tree exist. ``project_resource_root`` drags ``yaml``
into the closure, which crashes every default-entrypoint condition before
its first provider request (issue #99). The architecture suite pins the
container closure; this module is the host-only home for anything heavier.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest
from model_benchmark.declarations.scenario_locks import project_resource_root
from model_benchmark.runtime.conditions import ConditionAdapterError


def raw_api_condition_lock_path() -> Path:
    path = (
        project_resource_root("profiles", "published_profiles")
        / "functional-v1"
        / "raw-api-v1.condition.json"
    )
    if not path.is_file():
        raise ConditionAdapterError(
            "condition-lock-unavailable", "Raw API condition lock is unavailable"
        )
    return path


def raw_api_launch_shim_path() -> Path:
    path = Path(__file__).with_name("raw_api_launch.py")
    if not path.is_file():
        raise ConditionAdapterError(
            "launch-shim-unavailable", "Raw API launch shim is unavailable"
        )
    return path


def load_raw_api_condition_lock() -> tuple[bytes, Mapping[str, object], TypedDigest]:
    try:
        data = raw_api_condition_lock_path().read_bytes()
        value = load_canonical_json(data)
    except (OSError, CanonicalizationError) as error:
        raise ConditionAdapterError("invalid-condition-lock", str(error)) from error
    if not isinstance(value, dict):
        raise ConditionAdapterError(
            "invalid-condition-lock", "Raw API condition lock is not an object"
        )
    identity = TypedDigest.from_bytes(DigestKind.FUNCTIONAL_V1_CONDITION, data)
    return data, MappingProxyType(value), identity
