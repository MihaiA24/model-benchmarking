from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from typing import NoReturn


class CanonicalizationError(ValueError):
    """A value or byte stream violates the canonical JSON contract."""


def _fail(message: str) -> NoReturn:
    raise CanonicalizationError(message)


def _validate(value: object, path: str = "$") -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if not -(2**63) <= value <= 2**63 - 1:
            _fail(f"integer outside signed 64-bit range at {path}")
        return
    if isinstance(value, float):
        _fail(f"binary floating-point values are forbidden at {path}")
    if isinstance(value, str):
        if unicodedata.normalize("NFC", value) != value:
            _fail(f"string is not Unicode NFC at {path}")
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            _fail(f"string contains a surrogate code point at {path}")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                _fail(f"object key is not a string at {path}")
            _validate(key, f"{path}.<key>")
            _validate(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        if not isinstance(value, list):
            _fail(f"only JSON arrays represented as list are allowed at {path}")
        for index, child in enumerate(value):
            _validate(child, f"{path}[{index}]")
        return
    _fail(f"unsupported JSON value {type(value).__name__} at {path}")


def canonical_json_bytes(value: object) -> bytes:
    """Return the canonical UTF-8 representation of a JSON value."""
    _validate(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _reject_float(value: str) -> NoReturn:
    _fail(f"floating-point JSON number is forbidden: {value}")


def _reject_constant(value: str) -> NoReturn:
    _fail(f"non-JSON numeric constant is forbidden: {value}")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate object key: {key}")
        result[key] = value
    return result


def load_canonical_json(data: bytes) -> object:
    """Parse canonical JSON bytes, rejecting aliases and noncanonical encodings."""
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_object_without_duplicates,
            parse_float=_reject_float,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CanonicalizationError(str(error)) from error
    _validate(value)
    if canonical_json_bytes(value) != data:
        _fail("JSON bytes are valid but not in canonical form")
    return value
