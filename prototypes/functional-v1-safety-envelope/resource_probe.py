"""PROTOTYPE helper executed only inside disposable Docker containers."""

from __future__ import annotations

import os
import subprocess
import sys
import time


def memory() -> int:
    blocks: list[bytearray] = []
    while True:
        block = bytearray(8 * 1024 * 1024)
        for index in range(0, len(block), 4096):
            block[index] = 1
        blocks.append(block)
        print(f"allocated_mib={len(blocks) * 8}", flush=True)


def processes() -> int:
    children: list[subprocess.Popen[bytes]] = []
    try:
        while True:
            children.append(
                subprocess.Popen(
                    ["sleep", "60"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
    except OSError as error:
        print(f"spawned={len(children)} error={error}", flush=True)
        return 0
    finally:
        for child in children:
            child.terminate()
        for child in children:
            child.wait()


def cpu() -> int:
    started_wall = time.monotonic()
    started_cpu = time.process_time()
    value = 0
    while time.monotonic() - started_wall < 5:
        value = (value * 33 + 17) % 1_000_000_007
    print(
        f"pid={os.getpid()} wall={time.monotonic() - started_wall:.3f} "
        f"cpu={time.process_time() - started_cpu:.3f} value={value}",
        flush=True,
    )
    return 0


def main() -> int:
    modes = {"memory": memory, "processes": processes, "cpu": cpu}
    return modes[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
