FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
USER root
COPY baseline/ /workspace/repository/
RUN --network=none mkdir -p /workspace/repository && chown 65532:65532 /workspace/repository && chmod -R a+rwX /workspace/repository
USER 65532
WORKDIR /workspace/repository
# Example build: python -m compileall .
