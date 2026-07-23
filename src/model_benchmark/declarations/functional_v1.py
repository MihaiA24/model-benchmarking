from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, NoReturn
from urllib.parse import urlsplit, urlunsplit

import yaml
from yaml.constructor import ConstructorError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    load_canonical_json,
)
from model_benchmark.declarations.identities import (
    DigestKind,
    IdentityError,
    TypedDigest,
)
from model_benchmark.declarations.limits import FIXED_LIMITS
from model_benchmark.declarations.scenario_locks import schema_root_path
from model_benchmark.declarations.schemas import SchemaRegistry, SchemaValidationError


SCENARIOS = (
    "python-sales-by-genre",
    "spring-petvalidator-whitespace",
    "angular-reading-time",
    "react-author-filter",
)
CONDITIONS = ("omp", "opencode", "hermes", "raw-api")
NETWORK_POLICY = "proxy-only-v1"
MAX_PARALLEL = 3
_SECRET_FIELD = re.compile(
    r"(?:api[_-]?key|credential|password|secret|token[_-]?value)", re.IGNORECASE
)
_MODEL = re.compile(r"^[^\s\x00-\x1f\x7f]{1,256}$")
_ENVIRONMENT_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_SAFE_TEXT = re.compile(r"^[^\x00-\x1f\x7f]+$")


class FunctionalV1ManifestError(ValueError):
    """A Functional V1 declaration failed closed validation."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code

    def summary(self, command: str) -> dict[str, object]:
        return {
            "command": command,
            "message": str(self),
            "outcome": "rejected",
            "reason_code": self.reason_code,
        }


class _StrictYamlLoader(yaml.SafeLoader):
    def compose_node(self, parent: Node | None, index: int) -> Node | None:
        if self.check_event(AliasEvent):
            raise ConstructorError(
                None,
                None,
                "YAML aliases are forbidden",
                self.peek_event().start_mark,
            )
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise ConstructorError(
                None,
                None,
                "YAML anchors are forbidden",
                event.start_mark,
            )
        return super().compose_node(parent, index)

    def flatten_mapping(self, node: MappingNode) -> None:
        if any(key.value == "<<" for key, _ in node.value):
            raise ConstructorError(
                None,
                None,
                "YAML merge keys are forbidden",
                node.start_mark,
            )
        super().flatten_mapping(node)

    def construct_mapping(
        self,
        node: MappingNode,
        deep: bool = False,
    ) -> dict[Hashable, Any]:
        keys: set[Hashable] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise ConstructorError(
                    None,
                    None,
                    "YAML mapping keys must be scalar",
                    key_node.start_mark,
                )
            if key in keys:
                raise ConstructorError(
                    None,
                    None,
                    f"duplicate YAML key: {key!r}",
                    key_node.start_mark,
                )
            keys.add(key)
        return super().construct_mapping(node, deep=deep)


def _reject(reason_code: str, message: str) -> NoReturn:
    raise FunctionalV1ManifestError(reason_code, message)


def _strict_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        _reject(
            "invalid-manifest-schema",
            f"{label} must contain exactly: {', '.join(sorted(fields))}",
        )
    return value


def _read_regular_file_once(path: Path, *, label: str) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                _reject("invalid-input-file", f"{label} is not a regular file")
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except OSError as error:
        _reject("invalid-input-file", f"cannot read {label}: {error}")


def _safe_reference_path(raw_path: object, root: Path, *, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path or "\\" in raw_path:
        _reject("invalid-reference-path", f"{label} path must be a relative POSIX path")
    relative = PurePosixPath(raw_path)
    if (
        relative.is_absolute()
        or relative.as_posix() != raw_path
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        _reject("invalid-reference-path", f"{label} path is absolute or escaping")
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _reject("invalid-reference-path", f"{label} path contains a symlink")
    return current


def _validate_base_url(value: object) -> str:
    if not isinstance(value, str):
        _reject("invalid-provider-route", "provider.base_url must be a string")
    parsed = urlsplit(value)
    host = parsed.hostname
    try:
        port = parsed.port
    except ValueError as error:
        raise FunctionalV1ManifestError("invalid-provider-route", str(error)) from error
    if (
        parsed.scheme != "https"
        or host is None
        or host != host.lower()
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path in {"", "/"}
        or parsed.path.endswith("/")
        or "//" in parsed.path
        or "%" in parsed.path
        or "\\" in parsed.path
        or any(part in {".", ".."} for part in parsed.path.split("/"))
        or port == 443
        or urlunsplit(parsed) != value
    ):
        _reject(
            "invalid-provider-route",
            "provider.base_url must be a canonical HTTPS API root",
        )
    return value


def _validate_cost(value: object) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:0|[1-9]\d*)\.\d{2}", value) is None
    ):
        _reject(
            "invalid-cost-threshold",
            "stop_after_cost_usd_per_trial must be a canonical two-decimal string",
        )
    amount = Decimal(value)
    if not Decimal("0.01") <= amount <= Decimal("20.00"):
        _reject(
            "invalid-cost-threshold",
            "stop_after_cost_usd_per_trial must be between 0.01 and 20.00",
        )
    return value


def _pricing_rate(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"(?:0|[1-9]\d*)\.\d{1,9}", value) is None
    ):
        _reject(
            "invalid-pricing-record",
            f"provider.pricing.{label} must be a canonical decimal string",
        )
    rate = Decimal(value)
    if not Decimal("0") < rate <= Decimal("1000"):
        _reject(
            "invalid-pricing-record",
            f"provider.pricing.{label} must be positive and at most 1000",
        )
    return value


def _pricing_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value
    ) is None:
        _reject(
            "invalid-pricing-record",
            f"provider.pricing.{label} must be a whole-second UTC timestamp",
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise FunctionalV1ManifestError(
            "invalid-pricing-record", f"invalid provider.pricing.{label}"
        ) from error


def _validate_pricing_record(value: object) -> dict[str, Any]:
    record = _strict_object(
        value,
        {
            "currency",
            "effective_from_utc",
            "effective_until_utc",
            "identity",
            "input_usd_per_million_tokens",
            "output_usd_per_million_tokens",
            "retrieved_at_utc",
            "schema_version",
            "source_url",
            "unit",
        },
        "provider.pricing",
    )
    if (
        record["schema_version"] != 1
        or record["currency"] != "USD"
        or record["unit"] != "usd-per-million-tokens"
    ):
        _reject(
            "invalid-pricing-record",
            "provider.pricing must use schema version 1 USD per million tokens",
        )
    _pricing_rate(
        record["input_usd_per_million_tokens"],
        "input_usd_per_million_tokens",
    )
    _pricing_rate(
        record["output_usd_per_million_tokens"],
        "output_usd_per_million_tokens",
    )
    effective_from = _pricing_timestamp(
        record["effective_from_utc"], "effective_from_utc"
    )
    effective_until = _pricing_timestamp(
        record["effective_until_utc"], "effective_until_utc"
    )
    retrieved_at = _pricing_timestamp(record["retrieved_at_utc"], "retrieved_at_utc")
    if not effective_from <= retrieved_at < effective_until:
        _reject(
            "invalid-pricing-record",
            "provider.pricing retrieval must fall within its effective interval",
        )
    source = record["source_url"]
    if not isinstance(source, str):
        _reject("invalid-pricing-record", "provider.pricing.source_url is invalid")
    parsed_source = urlsplit(source)
    if (
        parsed_source.scheme != "https"
        or parsed_source.hostname is None
        or parsed_source.hostname != parsed_source.hostname.lower()
        or parsed_source.username is not None
        or parsed_source.password is not None
        or parsed_source.query
        or parsed_source.fragment
        or parsed_source.path in {"", "/"}
        or urlunsplit(parsed_source) != source
    ):
        _reject(
            "invalid-pricing-record",
            "provider.pricing.source_url must be a canonical HTTPS URL",
        )
    try:
        identity = TypedDigest.parse(record["identity"])
    except (IdentityError, TypeError) as error:
        raise FunctionalV1ManifestError(
            "invalid-pricing-record", "provider.pricing.identity is invalid"
        ) from error
    payload = {key: child for key, child in record.items() if key != "identity"}
    expected = TypedDigest.from_bytes(
        DigestKind.PRICING_RECORD, canonical_json_bytes(payload)
    )
    if identity != expected:
        _reject(
            "pricing-record-mismatch",
            "provider.pricing.identity does not match its canonical content",
        )
    return record


def _reject_secret_fields(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                _reject("invalid-manifest-schema", f"non-string field at {path}")
            if _SECRET_FIELD.search(key):
                _reject(
                    "secret-field-forbidden",
                    f"secret field is forbidden at {path}.{key}",
                )
            _reject_secret_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_secret_fields(child, f"{path}[{index}]")


def _validate_condition_lock(
    value: object,
    *,
    expected_condition: str,
) -> dict[str, object]:
    lock = _strict_object(
        value,
        {
            "adapter",
            "artifact",
            "condition",
            "evidence",
            "execution_profile",
            "image",
            "provider_mapping",
            "schema_version",
        },
        f"{expected_condition} condition lock",
    )
    if lock["schema_version"] != 1 or lock["condition"] != expected_condition:
        _reject(
            "condition-lock-mismatch",
            f"{expected_condition} condition lock identity mismatch",
        )
    artifact = _strict_object(
        lock["artifact"],
        {"digest", "kind", "platform"},
        f"{expected_condition}.artifact",
    )
    allowed_kinds = (
        {"raw-api-materializer"}
        if expected_condition == "raw-api"
        else {"native-executable"}
    )
    if (
        artifact["kind"] not in allowed_kinds
        or artifact["platform"] != "linux/amd64"
        or not isinstance(artifact["digest"], str)
        or re.fullmatch(r"artifact:sha256:[0-9a-f]{64}", artifact["digest"]) is None
    ):
        _reject("invalid-condition-lock", f"{expected_condition} artifact is invalid")
    image = _strict_object(
        lock["image"],
        {"content_digest", "kind", "mount_path", "platform", "read_only"},
        f"{expected_condition}.image",
    )
    if (
        image["kind"] != "condition-artifact-image"
        or image["platform"] != "linux/amd64"
        or image["mount_path"] != "/opt/model-benchmark-condition"
        or image["read_only"] is not True
        or not isinstance(image["content_digest"], str)
        or re.fullmatch(r"artifact:sha256:[0-9a-f]{64}", image["content_digest"])
        is None
    ):
        _reject(
            "invalid-condition-lock",
            f"{expected_condition} condition artifact image is invalid",
        )
    adapter = _strict_object(
        lock["adapter"],
        {
            "argv",
            "configuration",
            "environment_names",
            "harbor_agent",
            "non_interactive",
            "self_update",
            "working_directory",
        },
        f"{expected_condition}.adapter",
    )
    argv = adapter["argv"]
    environment_names = adapter["environment_names"]
    if (
        not isinstance(argv, list)
        or not argv
        or not all(
            isinstance(item, str) and item and "\x00" not in item for item in argv
        )
        or not isinstance(adapter["configuration"], dict)
        or adapter["harbor_agent"]
        != "model_benchmark.runtime.adapters.functional_v1:FunctionalV1ConditionAgent"
        or not isinstance(environment_names, list)
        or environment_names != sorted(set(environment_names))
        or not all(
            isinstance(name, str) and _ENVIRONMENT_NAME.fullmatch(name) is not None
            for name in environment_names
        )
        or adapter["non_interactive"] is not True
        or adapter["self_update"] is not False
        or adapter["working_directory"] != "/workspace"
    ):
        _reject("invalid-condition-lock", f"{expected_condition} adapter is invalid")
    provider = _strict_object(
        lock["provider_mapping"],
        {"base_url", "credential", "model"},
        f"{expected_condition}.provider_mapping",
    )
    if provider != {
        "base_url": "manifest-provider-base-url",
        "credential": "opaque-trial-proxy-token",
        "model": "manifest-provider-model",
    }:
        _reject(
            "invalid-condition-lock",
            f"{expected_condition} provider mapping is invalid",
        )
    evidence = _strict_object(
        lock["evidence"],
        {"required_paths"},
        f"{expected_condition}.evidence",
    )
    required_paths = evidence["required_paths"]
    if (
        not isinstance(required_paths, list)
        or required_paths != sorted(set(required_paths))
        or not all(
            isinstance(path, str) and _SAFE_TEXT.fullmatch(path) is not None
            for path in required_paths
        )
    ):
        _reject(
            "invalid-condition-lock",
            f"{expected_condition} evidence paths are invalid",
        )
    execution_profile = lock["execution_profile"]
    if (
        not isinstance(execution_profile, str)
        or re.fullmatch(r"execution-profile:sha256:[0-9a-f]{64}", execution_profile)
        is None
    ):
        _reject(
            "invalid-condition-lock",
            f"{expected_condition} execution profile is invalid",
        )
    return lock


def _load_reference(
    reference: object,
    *,
    root: Path,
    label: str,
    digest_kind: DigestKind,
    validate: Callable[[bytes], object],
) -> tuple[bytes, dict[str, object]]:
    declaration = _strict_object(reference, {"digest", "path"}, label)
    declared_digest = declaration["digest"]
    if not isinstance(declared_digest, str):
        _reject("invalid-reference-digest", f"{label} digest must be a string")
    try:
        parsed_digest = TypedDigest.parse(declared_digest)
    except IdentityError as error:
        raise FunctionalV1ManifestError(
            "invalid-reference-digest", str(error)
        ) from error
    if parsed_digest.kind is not digest_kind:
        _reject(
            "invalid-reference-digest",
            f"{label} requires a {digest_kind.value} digest",
        )
    path = _safe_reference_path(declaration["path"], root, label=label)
    data = _read_regular_file_once(path, label=label)
    if str(TypedDigest.from_bytes(digest_kind, data)) != declared_digest:
        _reject("reference-digest-mismatch", f"{label} digest mismatch")
    try:
        value = validate(data)
    except (CanonicalizationError, SchemaValidationError) as error:
        raise FunctionalV1ManifestError(
            "invalid-reference-schema",
            f"{label}: {error}",
        ) from error
    if not isinstance(value, dict):
        _reject("invalid-reference-schema", f"{label} must resolve to an object")
    return data, value


@dataclass(frozen=True)
class FunctionalV1Manifest:
    """Validated authored manifest plus captured immutable referenced inputs."""

    source_path: Path
    source_bytes: bytes
    value: Mapping[str, object]
    scenario_lock_bytes: Mapping[str, bytes]
    scenario_locks: Mapping[str, Mapping[str, object]]
    condition_lock_bytes: Mapping[str, bytes]
    condition_locks: Mapping[str, Mapping[str, object]]

    @property
    def source_yaml_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.source_bytes).hexdigest()}"

    @property
    def identity_value(self) -> dict[str, object]:
        conditions = self.value["conditions"]
        scenarios = self.value["scenarios"]
        assert isinstance(conditions, dict) and isinstance(scenarios, dict)
        return {
            "conditions": {
                name: {"digest": conditions[name]["digest"]} for name in CONDITIONS
            },
            "execution": self.value["execution"],
            "limits": self.value["limits"],
            "provider": self.value["provider"],
            "scenarios": {
                name: {"digest": scenarios[name]["digest"]} for name in SCENARIOS
            },
            "schema_version": 1,
        }

    @property
    def identity(self) -> TypedDigest:
        return TypedDigest.from_bytes(
            DigestKind.FUNCTIONAL_V1_MANIFEST,
            canonical_json_bytes(self.identity_value),
        )

    @property
    def resolved_value(self) -> dict[str, object]:
        return {
            "condition_locks": {
                name: dict(self.condition_locks[name]) for name in CONDITIONS
            },
            "manifest": self.identity_value,
            "manifest_identity": str(self.identity),
            "scenario_locks": {
                name: dict(self.scenario_locks[name]) for name in SCENARIOS
            },
            "schema_version": 1,
        }

    @property
    def resolved_identity(self) -> TypedDigest:
        return TypedDigest.from_bytes(
            DigestKind.RESOLVED_V1_MANIFEST,
            canonical_json_bytes(self.resolved_value),
        )

    @classmethod
    def load(cls, path: Path) -> "FunctionalV1Manifest":
        source_bytes = _read_regular_file_once(path, label="Run Manifest")
        try:
            text = source_bytes.decode("utf-8", errors="strict")
            if text.startswith("\ufeff"):
                _reject(
                    "invalid-manifest-yaml",
                    "Run Manifest must not contain a UTF-8 BOM",
                )
            raw_value = yaml.load(text, Loader=_StrictYamlLoader)
        except (UnicodeError, yaml.YAMLError) as error:
            raise FunctionalV1ManifestError(
                "invalid-manifest-yaml",
                str(error),
            ) from error
        manifest = _strict_object(
            raw_value,
            {
                "conditions",
                "execution",
                "limits",
                "provider",
                "scenarios",
                "schema_version",
            },
            "Run Manifest",
        )
        _reject_secret_fields(manifest)
        if manifest["schema_version"] != 1:
            _reject("unsupported-manifest-version", "schema_version must equal 1")
        provider = _strict_object(
            manifest["provider"], {"base_url", "model", "pricing"}, "provider"
        )
        _validate_base_url(provider["base_url"])
        _validate_pricing_record(provider["pricing"])
        if (
            not isinstance(provider["model"], str)
            or _MODEL.fullmatch(provider["model"]) is None
        ):
            _reject(
                "invalid-model",
                "provider.model must be one exact non-empty model slug",
            )
        limits = _strict_object(
            manifest["limits"],
            {
                "cpu_cores_per_trial",
                "memory_mib_per_trial",
                "provider_tokens_per_trial",
                "requests_per_trial",
                "stop_after_cost_usd_per_trial",
                "wall_time_seconds_per_trial",
                "writable_disk_mib_per_trial",
            },
            "limits",
        )
        for field, expected in FIXED_LIMITS.items():
            if limits[field] != expected or isinstance(limits[field], bool):
                _reject(
                    "fixed-envelope-mismatch",
                    f"limits.{field} must equal {expected}",
                )
        tokens = limits["provider_tokens_per_trial"]
        if (
            not isinstance(tokens, int)
            or isinstance(tokens, bool)
            or not 1 <= tokens <= 500_000
        ):
            _reject(
                "invalid-token-threshold",
                "provider_tokens_per_trial must be between 1 and 500000",
            )
        _validate_cost(limits["stop_after_cost_usd_per_trial"])
        execution = _strict_object(
            manifest["execution"], {"max_parallel", "network_policy"}, "execution"
        )
        if execution != {
            "max_parallel": MAX_PARALLEL,
            "network_policy": NETWORK_POLICY,
        }:
            _reject(
                "fixed-envelope-mismatch",
                f"execution must fix max_parallel={MAX_PARALLEL} and network_policy={NETWORK_POLICY}",
            )
        scenarios = _strict_object(manifest["scenarios"], set(SCENARIOS), "scenarios")
        conditions = _strict_object(
            manifest["conditions"], set(CONDITIONS), "conditions"
        )
        root = path.parent.resolve()
        registry = SchemaRegistry(schema_root_path())
        scenario_bytes: dict[str, bytes] = {}
        scenario_values: dict[str, Mapping[str, object]] = {}
        for name in SCENARIOS:
            data, lock = _load_reference(
                scenarios[name],
                root=root,
                label=f"scenarios.{name}",
                digest_kind=DigestKind.PACKAGE_LOCK,
                validate=registry.validate_bytes,
            )
            scenario_bytes[name] = data
            scenario_values[name] = MappingProxyType(lock)
        condition_bytes: dict[str, bytes] = {}
        condition_values: dict[str, Mapping[str, object]] = {}
        for name in CONDITIONS:
            data, lock = _load_reference(
                conditions[name],
                root=root,
                label=f"conditions.{name}",
                digest_kind=DigestKind.FUNCTIONAL_V1_CONDITION,
                validate=lambda captured, expected=name: _validate_condition_lock(
                    load_canonical_json(captured),
                    expected_condition=expected,
                ),
            )
            condition_bytes[name] = data
            condition_values[name] = MappingProxyType(lock)
        return cls(
            source_path=path.resolve(strict=False),
            source_bytes=source_bytes,
            value=MappingProxyType(manifest),
            scenario_lock_bytes=MappingProxyType(scenario_bytes),
            scenario_locks=MappingProxyType(scenario_values),
            condition_lock_bytes=MappingProxyType(condition_bytes),
            condition_locks=MappingProxyType(condition_values),
        )
