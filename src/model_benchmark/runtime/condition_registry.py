"""Immutable registry of the four Condition Adapters behind the seam.

This module — not ``conditions.py`` — imports the adapters, so the seam
types stay import-cycle-free (adapters import ``conditions``; nothing in
``conditions`` may import an adapter). Every host-side consumer resolves
per-condition behavior through ``CONDITIONS`` instead of string dispatch;
``HARNESS_CONDITIONS`` is derived from the registry's ``kind`` data.

The per-condition entrypoint scripts are emitted byte-identically to the
strings previously inlined in ``execution.py``; they are part of the
sealed condition-image build context, so their bytes are load-bearing.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from model_benchmark.runtime import hermes, omp, opencode, raw_api_locks
from model_benchmark.runtime.conditions import ConditionDefinition


_DEFAULT_ENTRYPOINT_SCRIPT = (
    "export PYTHONHOME=$ROOT/usr/local\n"
    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime\n"
    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/local/bin/python3.12 -m "
    'model_benchmark.runtime.condition_image "$@"\n'
)
_HERMES_ENTRYPOINT_SCRIPT = (
    "export PYTHONHOME=$ROOT/usr\n"
    "export PYTHONPATH=$ROOT/opt/model-benchmark-runtime:$ROOT/opt/hermes/.venv/lib/python3.13/site-packages\n"
    "exec $LOADER --library-path $LIBRARY_PATH $ROOT/usr/bin/python3 -m "
    'model_benchmark.runtime.condition_image "$@"\n'
)


CONDITIONS: Mapping[str, ConditionDefinition] = MappingProxyType(
    {
        "omp": ConditionDefinition(
            name="omp",
            kind="harness",
            lock_path=omp.omp_condition_lock_path,
            load_lock=omp.load_omp_condition_lock,
            launch_shim_path=omp.omp_launch_shim_path,
            validate_lock=omp.validate_omp_condition_lock,
            provision=omp.provision_omp,
            seal_process=omp.sealed_omp_process,
            evaluate_qualification=omp.evaluate_omp_qualification,
            entrypoint_script=_DEFAULT_ENTRYPOINT_SCRIPT,
        ),
        "opencode": ConditionDefinition(
            name="opencode",
            kind="harness",
            lock_path=opencode.opencode_condition_lock_path,
            load_lock=opencode.load_opencode_condition_lock,
            launch_shim_path=opencode.opencode_launch_shim_path,
            validate_lock=opencode.validate_opencode_condition_lock,
            provision=opencode.provision_opencode,
            seal_process=opencode.sealed_opencode_process,
            evaluate_qualification=opencode.evaluate_opencode_qualification,
            entrypoint_script=_DEFAULT_ENTRYPOINT_SCRIPT,
        ),
        "hermes": ConditionDefinition(
            name="hermes",
            kind="harness",
            lock_path=hermes.hermes_condition_lock_path,
            load_lock=hermes.load_hermes_condition_lock,
            launch_shim_path=hermes.hermes_launch_shim_path,
            validate_lock=hermes.validate_hermes_condition_lock,
            provision=hermes.provision_hermes,
            seal_process=hermes.sealed_hermes_process,
            evaluate_qualification=hermes.evaluate_hermes_qualification,
            image_base=hermes.HERMES_IMAGE_REFERENCE,
            entrypoint_script=_HERMES_ENTRYPOINT_SCRIPT,
        ),
        "raw-api": ConditionDefinition(
            name="raw-api",
            kind="baseline",
            lock_path=raw_api_locks.raw_api_condition_lock_path,
            load_lock=raw_api_locks.load_raw_api_condition_lock,
            launch_shim_path=raw_api_locks.raw_api_launch_shim_path,
            entrypoint_script=_DEFAULT_ENTRYPOINT_SCRIPT,
            requires_scenario_target=True,
        ),
    }
)

HARNESS_CONDITIONS = frozenset(
    name
    for name, definition in CONDITIONS.items()
    if definition.kind == "harness"
)
