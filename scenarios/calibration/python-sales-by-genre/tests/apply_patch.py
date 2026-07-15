#!/usr/bin/env python3
"""Apply the trusted single-file unified patch to a verifier-only baseline."""

from __future__ import annotations

import re
import sys
from pathlib import Path


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def apply(original: str, patch: str) -> str:
    source = original.splitlines(keepends=True)
    patch_lines = patch.splitlines(keepends=True)
    output: list[str] = []
    source_index = 0
    index = 0
    while index < len(patch_lines):
        match = HUNK.match(patch_lines[index])
        if match is None:
            index += 1
            continue
        old_start = int(match.group(1)) - 1
        if old_start < source_index:
            raise ValueError("overlapping patch hunks")
        output.extend(source[source_index:old_start])
        source_index = old_start
        index += 1
        while index < len(patch_lines) and not patch_lines[index].startswith("@@ ") and not patch_lines[index].startswith("diff --git "):
            line = patch_lines[index]
            if line.startswith("\\ No newline at end of file"):
                index += 1
                continue
            marker = line[:1]
            content = line[1:]
            if marker in {" ", "-"}:
                if source_index >= len(source) or source[source_index] != content:
                    raise ValueError("patch context does not match baseline")
                if marker == " ":
                    output.append(content)
                source_index += 1
            elif marker == "+":
                output.append(content)
            else:
                break
            index += 1
    output.extend(source[source_index:])
    return "".join(output)


def main() -> None:
    target = Path(sys.argv[1])
    patch = Path(sys.argv[2]).read_text(encoding="utf-8")
    if patch:
        target.write_text(apply(target.read_text(encoding="utf-8"), patch), encoding="utf-8")


if __name__ == "__main__":
    main()
