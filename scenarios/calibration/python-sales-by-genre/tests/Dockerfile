FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
USER root
COPY . /tests/
RUN --network=none chmod +x /tests/test.sh
USER 65532
WORKDIR /workspace/repository
# Example test: python -m pytest -q
