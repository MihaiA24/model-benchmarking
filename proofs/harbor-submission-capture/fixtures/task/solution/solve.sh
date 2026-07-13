#!/bin/sh
set -eu
printf 'after\n' > src/app.txt
printf 'new\n' > src/new.txt
mkdir -p /workspace/agent-home/cache
printf 'must-not-cross\n' > /workspace/agent-home/cache/secret.txt
