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


_ENTRY_PROPERTIES = {
    "file": {"pattern": r"^[^/]+\.schema\.json$", "type": "string"},
    "name": {"minLength": 1, "type": "string"},
    "sha256": {"type": "string"},
    "version": {"minimum": 1, "type": "integer"},
}
_CATALOG_VALIDATOR = Draft202012Validator(
    {
        "additionalProperties": False,
        "properties": {
            "canonicalization": {
                "additionalProperties": False,
                "properties": {
                    **_ENTRY_PROPERTIES,
                    "file": {"pattern": r"^[^/]+$", "type": "string"},
                    "name": {"const": "model-benchmark/canonical-json"},
                    "version": {"const": 1},
                },
                "required": ["file", "name", "sha256", "version"],
                "type": "object",
            },
            "schemas": {
                "items": {
                    "additionalProperties": False,
                    "properties": _ENTRY_PROPERTIES,
                    "required": ["file", "name", "sha256", "version"],
                    "type": "object",
                },
                "minItems": 1,
                "type": "array",
            },
            "version": {"const": 1},
        },
        "required": ["canonicalization", "schemas", "version"],
        "type": "object",
    }
)


class SchemaRegistry:
    """Strict loader for the repository's published schema catalog."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        try:
            catalog_value = load_canonical_json((self._root / "catalog.json").read_bytes())
        except (OSError, CanonicalizationError) as error:
            raise SchemaValidationError(f"invalid schema catalog: {error}") from error
        catalog_error = next(_CATALOG_VALIDATOR.iter_errors(catalog_value), None)
        if catalog_error is not None:
            raise SchemaValidationError(
                f"invalid schema catalog: {catalog_error.message}"
            )
        raw_canonicalization = catalog_value["canonicalization"]
        canonicalization = SchemaEntry(
            name=raw_canonicalization["name"],
            version=raw_canonicalization["version"],
            file=raw_canonicalization["file"],
            sha256=raw_canonicalization["sha256"],
        )
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

        entries: list[SchemaEntry] = []
        validators: dict[tuple[str, int], Draft202012Validator] = {}
        for raw_entry in catalog_value["schemas"]:
            entry = SchemaEntry(
                name=raw_entry["name"],
                version=raw_entry["version"],
                file=raw_entry["file"],
                sha256=raw_entry["sha256"],
            )
            key = (entry.name, entry.version)
            if key in validators:
                raise SchemaValidationError(f"duplicate schema identity: {key}")
            try:
                schema_bytes = (self._root / entry.file).read_bytes()
                schema = load_canonical_json(schema_bytes)
                digest = str(TypedDigest.from_bytes(DigestKind.SCHEMA, schema_bytes))
            except (OSError, CanonicalizationError) as error:
                raise SchemaValidationError(
                    f"invalid published schema {entry.file}: {error}"
                ) from error
            if digest != entry.sha256:
                raise SchemaValidationError(
                    f"published schema digest mismatch: {entry.file}"
                )
            if not isinstance(schema, dict):
                raise SchemaValidationError(
                    f"published schema is not an object: {entry.file}"
                )
            if (
                schema.get("x-model-benchmark-schema-name") != entry.name
                or schema.get("x-model-benchmark-schema-version") != entry.version
            ):
                raise SchemaValidationError(
                    f"published schema identity mismatch: {entry.file}"
                )
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as error:
                raise SchemaValidationError(
                    f"invalid JSON Schema {entry.file}: {error}"
                ) from error
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

    def entry(self, name: str, version: int) -> SchemaEntry:
        entry = next(
            (
                item
                for item in self._entries
                if item.name == name and item.version == version
            ),
            None,
        )
        if entry is None:
            raise SchemaValidationError(f"unknown schema identity: {name} v{version}")
        return entry

    def envelope(self, name: str, version: int) -> dict[str, object]:
        entry = self.entry(name, version)
        return {
            "canonicalization_sha256": self._canonicalization.sha256,
            "canonicalization_version": self._canonicalization.version,
            "name": entry.name,
            "sha256": entry.sha256,
            "version": entry.version,
        }

    def validate_value(
        self,
        value: object,
        *,
        name: str,
        version: int,
    ) -> dict[str, object]:
        if not isinstance(value, dict):
            raise SchemaValidationError("document must be an object")
        entry = self.entry(name, version)
        errors = sorted(
            self._validators[(entry.name, entry.version)].iter_errors(value),
            key=lambda item: item.json_path,
        )
        if errors:
            first = errors[0]
            raise SchemaValidationError(f"{first.json_path}: {first.message}")
        return value

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
        entry = self.entry(name, version)
        if digest != entry.sha256:
            raise SchemaValidationError("document schema digest does not match the catalog")
        return self.validate_value(value, name=name, version=version)
