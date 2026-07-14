from __future__ import annotations

import fnmatch
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


class PolicyError(ValueError):
    """The repository verification policy or changed-path input is invalid."""


DOMAINS = (
    "development",
    "cached_integration",
    "fresh_authoritative",
    "ci_acceptance",
    "trial_verifier",
    "runtime_preflight",
    "provisioning_preflight",
)


@dataclass(frozen=True)
class Change:
    status: str
    path: str
    previous_path: str | None = None


@dataclass(frozen=True)
class Selection:
    changes: tuple[Change, ...]
    development: tuple[str, ...]
    cached_integration: tuple[str, ...]
    fresh_gates: tuple[str, ...]
    fallback: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    path: Path
    value: dict[str, object]
    sha256: str

    @property
    def repository(self) -> str:
        return _string(self.value["repository"], "repository")

    @property
    def broad_development_slice(self) -> str:
        return _string(
            self.value["broad_development_slice"],
            "broad_development_slice",
        )

    @property
    def development_slices(self) -> dict[str, dict[str, object]]:
        return _indexed(self.value["development_slices"], "development_slices")

    @property
    def cached_integration_slices(self) -> dict[str, dict[str, object]]:
        return _indexed(
            self.value["cached_integration_slices"],
            "cached_integration_slices",
        )

    @property
    def fresh_gates(self) -> dict[str, dict[str, object]]:
        return _indexed(self.value["fresh_gates"], "fresh_gates")

    @property
    def path_rules(self) -> tuple[dict[str, object], ...]:
        rules = self.value["path_rules"]
        assert isinstance(rules, list)
        return tuple(rules)

    def audit_paths(self, paths: Iterable[str]) -> tuple[str, ...]:
        return tuple(sorted(path for path in paths if not self._matching_rules(path)))

    def select(self, changes: Iterable[Change]) -> Selection:
        normalized = tuple(changes)
        development: set[str] = set()
        cached: set[str] = set()
        gates: set[str] = set()
        reasons: list[str] = []
        fallback = False

        if not normalized:
            development.add(self.broad_development_slice)
            fallback = True
            reasons.append("no changed paths were supplied")

        for change in normalized:
            if change.status != "M":
                fallback = True
                reasons.append(
                    f"{change.status} change requires closed-world fallback: {change.path}"
                )
            candidates = (change.path,) + (
                (change.previous_path,) if change.previous_path is not None else ()
            )
            matched = False
            for candidate in candidates:
                for rule in self._matching_rules(candidate):
                    matched = True
                    development.update(_string_list(rule["development"], "development"))
                    cached.update(
                        _string_list(rule["cached_integration"], "cached_integration")
                    )
                    gates.update(_string_list(rule["fresh_gates"], "fresh_gates"))
            if not matched:
                fallback = True
                reasons.append(f"unclassified path requires closed-world fallback: {change.path}")

        if fallback:
            development = {self.broad_development_slice}
            gates.update(self.fresh_gates)

        return Selection(
            changes=normalized,
            development=tuple(sorted(development)),
            cached_integration=tuple(sorted(cached)),
            fresh_gates=tuple(sorted(gates)),
            fallback=fallback,
            reasons=tuple(sorted(set(reasons))),
        )

    def selection_document(self, selection: Selection) -> dict[str, object]:
        return {
            "authority": "non_authoritative",
            "cached_integration": [
                self.cached_integration_slices[name]
                for name in selection.cached_integration
            ],
            "changes": [
                {
                    "path": change.path,
                    "previous_path": change.previous_path,
                    "status": change.status,
                }
                for change in selection.changes
            ],
            "development": [
                self.development_slices[name] for name in selection.development
            ],
            "diagnostics": {
                "changed_path_count": len(selection.changes),
                "shape": "verification-selection-diagnostics-v1",
            },
            "fallback": selection.fallback,
            "fresh_authoritative": [
                self.fresh_gates[name] for name in selection.fresh_gates
            ],
            "policy_sha256": self.sha256,
            "reasons": list(selection.reasons),
            "schema": "verification-selection-v1",
        }

    def _matching_rules(self, path: str) -> tuple[dict[str, object], ...]:
        return tuple(
            rule
            for rule in self.path_rules
            if any(
                fnmatch.fnmatchcase(path, pattern)
                for pattern in _string_list(rule["patterns"], "patterns")
            )
        )


def load_policy(path: Path) -> Policy:
    try:
        data = path.read_bytes()
        value = json.loads(data)
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot load verification policy: {error}") from error
    if not isinstance(value, dict):
        raise PolicyError("verification policy must be an object")
    required = {
        "broad_development_slice",
        "cached_integration_slices",
        "development_slices",
        "domains",
        "fresh_gates",
        "non_authoritative",
        "path_rules",
        "repository",
        "version",
    }
    if set(value) != required:
        raise PolicyError("verification policy has unknown or missing fields")
    if value["version"] != 1 or value["non_authoritative"] is not True:
        raise PolicyError("unsupported verification policy")
    if tuple(_string_list(value["domains"], "domains")) != DOMAINS:
        raise PolicyError("verification policy domains are incomplete or reordered")

    development = _indexed(value["development_slices"], "development_slices")
    cached = _indexed(value["cached_integration_slices"], "cached_integration_slices")
    gates = _indexed(value["fresh_gates"], "fresh_gates")
    broad = _string(value["broad_development_slice"], "broad_development_slice")
    if broad not in development:
        raise PolicyError("broad development slice is undefined")

    for name, slice_value in development.items():
        _strict_keys(slice_value, {"authority", "commands", "id"}, name)
        if slice_value["authority"] != "none":
            raise PolicyError(f"development slice {name} must have no authority")
        _commands(slice_value["commands"], name)
    for name, slice_value in cached.items():
        _strict_keys(slice_value, {"authority", "commands", "id"}, name)
        if slice_value["authority"] != "diagnostic":
            raise PolicyError(f"integration slice {name} must be diagnostic")
        _commands(slice_value["commands"], name)
    for name, gate in gates.items():
        _strict_keys(
            gate,
            {
                "check_name",
                "commands",
                "docker_required",
                "id",
                "trusted_app_slug",
                "worker_classes",
                "workflow_path",
            },
            name,
        )
        _string(gate["check_name"], f"{name}.check_name")
        _string(gate["trusted_app_slug"], f"{name}.trusted_app_slug")
        _string(gate["workflow_path"], f"{name}.workflow_path")
        _string_list(gate["worker_classes"], f"{name}.worker_classes")
        if not isinstance(gate["docker_required"], bool):
            raise PolicyError(f"{name}.docker_required must be boolean")
        raw_commands = gate["commands"]
        if not isinstance(raw_commands, list) or not raw_commands:
            raise PolicyError(f"{name}.commands must be a non-empty list")
        command_ids: set[str] = set()
        for command in raw_commands:
            if not isinstance(command, dict):
                raise PolicyError(f"{name}.commands entries must be objects")
            _strict_keys(
                command,
                {"acceptance_artifact", "case_inventory", "command", "id"},
                f"{name}.commands",
            )
            command_id = _string(command["id"], f"{name}.command.id")
            if command_id in command_ids:
                raise PolicyError(f"duplicate command id in {name}: {command_id}")
            command_ids.add(command_id)
            _string(command["command"], f"{name}.{command_id}.command")
            inventory = command["case_inventory"]
            artifact = command["acceptance_artifact"]
            if inventory not in {"none", "required"}:
                raise PolicyError(f"invalid case inventory in {name}: {command_id}")
            if inventory == "required":
                _string(artifact, f"{name}.{command_id}.acceptance_artifact")
            elif artifact is not None:
                raise PolicyError(f"non-case command cannot name an artifact: {command_id}")

    rules = value["path_rules"]
    if not isinstance(rules, list) or not rules:
        raise PolicyError("path_rules must be a non-empty list")
    rule_ids: set[str] = set()
    for rule in rules:
        if not isinstance(rule, dict):
            raise PolicyError("path rule must be an object")
        _strict_keys(
            rule,
            {
                "cached_integration",
                "classification",
                "development",
                "domains",
                "fresh_gates",
                "id",
                "patterns",
            },
            "path_rule",
        )
        rule_id = _string(rule["id"], "path_rule.id")
        if rule_id in rule_ids:
            raise PolicyError(f"duplicate path rule: {rule_id}")
        rule_ids.add(rule_id)
        patterns = _string_list(rule["patterns"], f"{rule_id}.patterns")
        if not patterns:
            raise PolicyError(f"path rule has no patterns: {rule_id}")
        classification = rule["classification"]
        domains = _string_list(rule["domains"], f"{rule_id}.domains")
        selected_development = _string_list(
            rule["development"], f"{rule_id}.development"
        )
        selected_cached = _string_list(
            rule["cached_integration"], f"{rule_id}.cached_integration"
        )
        selected_gates = _string_list(rule["fresh_gates"], f"{rule_id}.fresh_gates")
        if classification == "non_normative_docs":
            if domains or selected_development or selected_cached or selected_gates:
                raise PolicyError(f"docs-only rule selects verification work: {rule_id}")
        elif classification != "normative" or not domains or not selected_development:
            raise PolicyError(f"normative path rule is incomplete: {rule_id}")
        if not set(domains).issubset(DOMAINS):
            raise PolicyError(f"unknown domain in path rule: {rule_id}")
        if not set(selected_development).issubset(development):
            raise PolicyError(f"unknown development slice in path rule: {rule_id}")
        if not set(selected_cached).issubset(cached):
            raise PolicyError(f"unknown integration slice in path rule: {rule_id}")
        if not set(selected_gates).issubset(gates):
            raise PolicyError(f"unknown gate in path rule: {rule_id}")

    return Policy(path=path, value=value, sha256=hashlib.sha256(data).hexdigest())


def changes_from_git(project_root: Path, base: str, head: str) -> tuple[Change, ...]:
    if not base or not head:
        raise PolicyError("both --base and --head are required")
    try:
        completed = subprocess.run(
            [
                "git",
                "diff",
                "--name-status",
                "-z",
                "--find-renames",
                base,
                head,
                "--",
            ],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PolicyError(f"cannot derive changed paths from Git: {error}") from error
    fields = completed.stdout.decode("utf-8").split("\0")
    if fields and fields[-1] == "":
        fields.pop()
    changes: list[Change] = []
    index = 0
    while index < len(fields):
        status_field = fields[index]
        index += 1
        status = status_field[:1]
        if status in {"R", "C"}:
            if index + 1 >= len(fields):
                raise PolicyError("truncated Git rename/copy record")
            previous = _normalize_path(fields[index])
            path = _normalize_path(fields[index + 1])
            index += 2
            changes.append(Change(status=status, path=path, previous_path=previous))
        else:
            if index >= len(fields):
                raise PolicyError("truncated Git changed-path record")
            path = _normalize_path(fields[index])
            index += 1
            changes.append(Change(status=status, path=path))
    return tuple(changes)


def changes_from_file(path: Path) -> tuple[Change, ...]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise PolicyError(f"cannot read changed-path file: {error}") from error
    changes: list[Change] = []
    for line_number, line in enumerate(lines, 1):
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) == 1:
            changes.append(Change(status="M", path=_normalize_path(fields[0])))
            continue
        status = fields[0][:1]
        if status in {"R", "C"} and len(fields) == 3:
            changes.append(
                Change(
                    status=status,
                    path=_normalize_path(fields[2]),
                    previous_path=_normalize_path(fields[1]),
                )
            )
        elif status not in {"R", "C"} and len(fields) == 2:
            changes.append(Change(status=status, path=_normalize_path(fields[1])))
        else:
            raise PolicyError(f"malformed changed-path record at line {line_number}")
    return tuple(changes)


def tracked_paths(project_root: Path) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise PolicyError(f"cannot enumerate tracked paths: {error}") from error
    return tuple(
        _normalize_path(item)
        for item in completed.stdout.decode("utf-8").split("\0")
        if item
    )


def _normalize_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise PolicyError(f"unsafe changed path: {value!r}")
    return path.as_posix()


def _indexed(value: object, field: str) -> dict[str, dict[str, object]]:
    if not isinstance(value, list):
        raise PolicyError(f"{field} must be a list")
    result: dict[str, dict[str, object]] = {}
    for item in value:
        if not isinstance(item, dict):
            raise PolicyError(f"{field} entries must be objects")
        name = _string(item.get("id"), f"{field}.id")
        if name in result:
            raise PolicyError(f"duplicate {field} id: {name}")
        result[name] = item
    return result


def _commands(value: object, field: str) -> tuple[str, ...]:
    commands = _string_list(value, f"{field}.commands")
    if not commands:
        raise PolicyError(f"{field}.commands must not be empty")
    return commands


def _strict_keys(value: dict[str, object], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise PolicyError(f"{field} has unknown or missing fields")


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{field} must be a non-empty string")
    return value


def _string_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise PolicyError(f"{field} must be a string list")
    return tuple(value)
