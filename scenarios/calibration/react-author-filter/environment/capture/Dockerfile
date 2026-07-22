FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
WORKDIR /opt/capture
COPY capture/capture.py capture/policy.json /opt/capture/
COPY baseline/ /opt/capture/baseline/
RUN --network=none chmod -R a=rX /opt/capture && install -d -o 65532 -g 65532 -m 0700 /capture
USER 65532:65532
