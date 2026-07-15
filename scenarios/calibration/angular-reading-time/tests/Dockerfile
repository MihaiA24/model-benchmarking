FROM node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0
USER root
COPY . /tests/
RUN --network=none chmod +x /tests/test.sh
USER 65532
WORKDIR /workspace/repository
# Example test: npm test -- --runInBand
