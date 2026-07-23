FROM node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0
USER root
COPY evaluator/runner.mjs /opt/evaluator/runner.mjs
RUN --network=none chmod -R a=rX /opt/evaluator
USER 65532:65532
WORKDIR /opt/evaluator
ENTRYPOINT ["timeout", "--signal=TERM", "--kill-after=2s", "90s", "node", "--experimental-vm-modules", "/opt/evaluator/runner.mjs"]
