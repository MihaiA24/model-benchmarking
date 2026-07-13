from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from model_benchmark.declarations.canonical import (
    CanonicalizationError,
    load_canonical_json,
)
from model_benchmark.declarations.identities import DigestKind, TypedDigest


class SchemaValidationError(ValueError):
    """A schema, catalog, or document failed closed validation."""


@dataclass(frozen=True)
class SchemaEntry:
    name: str
    version: int
    file: str
    sha256: str


class SchemaRegistry:
    """Strict loader for the repository's published schema catalog."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        try:
            catalog_value = load_canonical_json((self._root / "catalog.json").read_bytes())
        except (OSError, CanonicalizationError) as error:
            raise SchemaValidationError(f"invalid schema catalog: {error}") from error
        if not isinstance(catalog_value, dict) or set(catalog_value) != {
            "canonicalization",
            "schemas",
            "version",
        }:
            raise SchemaValidationError("schema catalog has unknown or missing fields")
        if catalog_value["version"] != 1:
            raise SchemaValidationError("unsupported schema catalog version")
        raw_canonicalization = catalog_value["canonicalization"]
        if not isinstance(raw_canonicalization, dict) or set(raw_canonicalization) != {
            "file",
            "name",
            "sha256",
            "version",
        }:
            raise SchemaValidationError("canonicalization catalog entry is not strict")
        if (
            not isinstance(raw_canonicalization["file"], str)
            or not isinstance(raw_canonicalization["name"], str)
            or not isinstance(raw_canonicalization["sha256"], str)
            or not isinstance(raw_canonicalization["version"], int)
            or isinstance(raw_canonicalization["version"], bool)
        ):
            raise SchemaValidationError(
                "canonicalization catalog entry contains invalid values"
            )
        canonicalization = SchemaEntry(
            name=raw_canonicalization["name"],
            version=raw_canonicalization["version"],
            file=raw_canonicalization["file"],
            sha256=raw_canonicalization["sha256"],
        )
        if (
            canonicalization.name != "model-benchmark/canonical-json"
            or canonicalization.version != 1
            or Path(canonicalization.file).name != canonicalization.file
        ):
            raise SchemaValidationError("unsupported canonicalization identity")
        try:
            canonicalization_bytes = (
                self._root / canonicalization.file
            ).read_bytes()
            canonicalization_value = load_canonical_json(canonicalization_bytes)
            canonicalization_digest = str(
                TypedDigest.from_bytes(
                    DigestKind.CANONICALIZATION,
                    canonicalization_bytes,
                )
            )
        except (OSError, CanonicalizationError) as error:
            raise SchemaValidationError(
                f"invalid canonicalization contract: {error}"
            ) from error
        if (
            canonicalization_digest != canonicalization.sha256
            or not isinstance(canonicalization_value, dict)
            or canonicalization_value.get("contract") != canonicalization.name
            or canonicalization_value.get("version") != canonicalization.version
        ):
            raise SchemaValidationError("canonicalization contract identity mismatch")
        self._canonicalization = canonicalization
        raw_entries = catalog_value["schemas"]
        if not isinstance(raw_entries, list) or not raw_entries:
            raise SchemaValidationError("schema catalog must contain schemas")

        entries: list[SchemaEntry] = []
        validators: dict[tuple[str, int], Draft202012Validator] = {}
        for raw_entry in raw_entries:
            if not isinstance(raw_entry, dict) or set(raw_entry) != {
                "file",
                "name",
                "sha256",
                "version",
            }:
                raise SchemaValidationError("schema catalog entry is not strict")
            file = raw_entry["file"]
            name = raw_entry["name"]
            version = raw_entry["version"]
            sha256 = raw_entry["sha256"]
            if (
                not isinstance(file, str)
                or Path(file).name != file
                or not file.endswith(".schema.json")
                or not isinstance(name, str)
                or not name
                or not isinstance(version, int)
                or isinstance(version, bool)
                or version < 1
                or not isinstance(sha256, str)
            ):
                raise SchemaValidationError("schema catalog entry contains invalid values")
            entry = SchemaEntry(name=name, version=version, file=file, sha256=sha256)
            key = (entry.name, entry.version)
            if key in validators:
                raise SchemaValidationError(f"duplicate schema identity: {key}")
            try:
                schema_bytes = (self._root / entry.file).read_bytes()
                schema = load_canonical_json(schema_bytes)
                digest = str(TypedDigest.from_bytes(DigestKind.SCHEMA, schema_bytes))
            except (OSError, CanonicalizationError) as error:
                raise SchemaValidationError(f"invalid published schema {file}: {error}") from error
            if digest != entry.sha256:
                raise SchemaValidationError(f"published schema digest mismatch: {file}")
            if not isinstance(schema, dict):
                raise SchemaValidationError(f"published schema is not an object: {file}")
            if (
                schema.get("x-model-benchmark-schema-name") != name
                or schema.get("x-model-benchmark-schema-version") != version
            ):
                raise SchemaValidationError(f"published schema identity mismatch: {file}")
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise SchemaValidationError(f"invalid JSON Schema {file}: {error}") from error
            entries.append(entry)
            validators[key] = Draft202012Validator(schema)

        if entries != sorted(entries, key=lambda item: (item.name, item.version)):
            raise SchemaValidationError("schema catalog entries are not canonically ordered")
        self._entries = tuple(entries)
        self._validators = validators

    @property
    def entries(self) -> tuple[SchemaEntry, ...]:
        return self._entries

    @property
    def canonicalization(self) -> SchemaEntry:
        return self._canonicalization

    def validate_path(self, path: Path) -> dict[str, object]:
        try:
            return self.validate_bytes(path.read_bytes())
        except OSError as error:
            raise SchemaValidationError(f"cannot read document: {path}") from error

    def validate_bytes(self, data: bytes) -> dict[str, object]:
        try:
            value = load_canonical_json(data)
        except CanonicalizationError as error:
            raise SchemaValidationError(f"document is not canonical JSON: {error}") from error
        if not isinstance(value, dict):
            raise SchemaValidationError("document must be an object")
        envelope = value.get("schema")
        if not isinstance(envelope, dict) or set(envelope) != {
            "canonicalization_sha256",
            "canonicalization_version",
            "name",
            "sha256",
            "version",
        }:
            raise SchemaValidationError("document schema envelope is not strict")
        name = envelope["name"]
        version = envelope["version"]
        digest = envelope["sha256"]
        canonicalization_version = envelope["canonicalization_version"]
        canonicalization_digest = envelope["canonicalization_sha256"]
        if (
            not isinstance(name, str)
            or not isinstance(version, int)
            or isinstance(version, bool)
            or not isinstance(digest, str)
            or canonicalization_version != self._canonicalization.version
            or canonicalization_digest != self._canonicalization.sha256
        ):
            raise SchemaValidationError("document schema identity is malformed")
        key = (name, version)
        entry = next(
            (item for item in self._entries if (item.name, item.version) == key),
            None,
        )
        if entry is None:
            raise SchemaValidationError(f"unknown schema identity: {name} v{version}")
        if digest != entry.sha256:
            raise SchemaValidationError("document schema digest does not match the catalog")
        errors = sorted(
            self._validators[key].iter_errors(value),
            key=lambda item: item.json_path,
        )
        if errors:
            first = errors[0]
            raise SchemaValidationError(f"{first.json_path}: {first.message}")
        return value
