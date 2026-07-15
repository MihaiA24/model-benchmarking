#!/bin/sh
# MODEL_BENCHMARK_HIDDEN:replace-with-private-verifier-canary
set -u
prlimit --pid $$ --nproc=256:256
repository=/tmp/submitted-repository
root=/tmp/petvalidator-verifier
classes=/tmp/petvalidator-classes
mkdir -p "$repository" "$root" "$classes" /logs/verifier
tar -xf /tests/baseline.tar -C "$repository"
if [ -s /capture/submission.patch ]; then
  git -C "$repository" apply --whitespace=nowarn /capture/submission.patch
fi
cp -R /tests/java/. "$root/"
target=org/springframework/samples/petclinic/owner/PetValidator.java
cp "$repository/src/main/java/$target" "$root/$target"
acceptance=0
regression=0
domain=0
if javac -d "$classes" $(find "$root" -name '*.java' -type f); then
  if java -cp "$classes" org.springframework.samples.petclinic.owner.PetValidatorBehavior acceptance; then acceptance=1; fi
  if java -cp "$classes" org.springframework.samples.petclinic.owner.PetValidatorBehavior regression; then regression=1; fi
  if java -cp "$classes" org.springframework.samples.petclinic.owner.PetValidatorBehavior domain; then domain=1; fi
fi
status() { if [ "$1" -eq 1 ]; then printf pass; else printf fail; fi; }
acceptance_status=$(status "$acceptance")
regression_status=$(status "$regression")
domain_status=$(status "$domain")
if [ "$acceptance" -eq 1 ] && [ "$regression" -eq 1 ] && [ "$domain" -eq 1 ]; then task_success=true; task_score=1; else task_success=false; task_score=0; fi
printf '%s\n' "{\"acceptance_score\":${acceptance},\"validation_behavior\":${domain},\"checks\":[{\"evidence\":[\"PetValidator.java\",\"space-name-case\"],\"id\":\"space-name\",\"status\":\"${acceptance_status}\"},{\"evidence\":[\"PetValidator.java\",\"adjacent-validation-matrix\"],\"id\":\"validator-regression\",\"status\":\"${regression_status}\"},{\"evidence\":[\"whitespace-behavior-matrix\"],\"id\":\"whitespace-matrix\",\"status\":\"${domain_status}\"}],\"domain_scores\":{\"validation_behavior\":${domain}},\"regression_score\":${regression},\"required_group_statuses\":{\"space-name\":\"${acceptance_status}\",\"validator-regression\":\"${regression_status}\",\"whitespace-matrix\":\"${domain_status}\"},\"task_success\":${task_success},\"verifier_complete\":true}" > /logs/verifier/verifier-result.json
printf '%s\n' "{\"acceptance_score\":${acceptance},\"regression_score\":${regression},\"task_success\":${task_score},\"validation_behavior\":${domain}}" > /logs/verifier/reward.json
