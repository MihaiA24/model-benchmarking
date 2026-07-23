FROM node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0
USER root
COPY . /tests/
RUN --network=none chmod -R a=rX /tests \
    && chmod +x /tests/test.sh \
    && install -d -o 65532 -g 65532 -m 0700 /capture /evaluator-repository /evaluator-request /evaluator-result /workspace/repository
USER 65532:65532
WORKDIR /tests
