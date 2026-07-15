#!/bin/sh
# MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary
set -eu
prlimit --pid $$ --nproc=256:256
root=/tmp/submitted-repository
mkdir -p "$root"
tar -xf /tests/baseline.tar -C "$root"
if [ -s /capture/submission.patch ]; then
  python3 /tests/apply_patch.py "$root/sales_by_genre.py" /capture/submission.patch
fi
cd "$root"
python3 /tests/verify.py
