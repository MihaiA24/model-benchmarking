#!/bin/sh
# MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary
set -eu
prlimit --pid $$ --nproc=256:256
root=/tmp/submitted-repository
mkdir -p "$root"
tar -xf /tests/baseline.tar -C "$root"
if [ -s /capture/submission.patch ]; then
  node /tests/apply-patch.mjs "$root/src/app/features/article/components/article-preview.component.ts" /capture/submission.patch
fi
node /tests/verify.mjs
