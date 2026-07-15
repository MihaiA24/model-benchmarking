#!/bin/sh
# MODEL_BENCHMARK_HIDDEN:replace-with-reference-solution-canary
set -eu
file=/workspace/repository/src/main/java/org/springframework/samples/petclinic/owner/PetValidator.java
count=$(grep -c 'StringUtils.hasLength(name)' "$file")
[ "$count" -eq 1 ]
sed -i 's/StringUtils\.hasLength(name)/StringUtils.hasText(name)/' "$file"
