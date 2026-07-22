#!/bin/sh
# MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary
set -eu
prlimit --pid $$ --nproc=256:256
root=/evaluator-repository
for directory in "$root" /evaluator-request /evaluator-result; do
  [ -d "$directory" ] && [ -w "$directory" ]
done
[ ! -e /evaluator-request/request.json ]
[ ! -e /evaluator-result/result.json ]
tar -xf /tests/baseline.tar -C "$root"
if [ -s /capture/submission.patch ]; then
  node /tests/apply-patch.mjs "$root/src/reducers/articleList.js" /capture/submission.patch
fi
node /tests/verify.mjs
