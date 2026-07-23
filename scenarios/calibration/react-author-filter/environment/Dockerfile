FROM node:22.17.0-bookworm-slim@sha256:b04ce4ae4e95b522112c2e5c52f781471a5cbc3b594527bcddedee9bc48c03a0
USER root
COPY dependencies/package.json dependencies/package-lock.json dependencies/node_modules.tar.gz dependencies/node_modules.tar.gz.sha256 /opt/react-dependencies/
RUN --network=none cd /opt/react-dependencies \
    && sha256sum -c node_modules.tar.gz.sha256 \
    && mkdir -p /workspace \
    && tar -xzf node_modules.tar.gz -C /workspace \
    && rm node_modules.tar.gz \
    && chmod -R a=rX /workspace/node_modules
COPY baseline/ /workspace/repository/
RUN --network=none mkdir -p /workspace/repository \
    && chown 65532:65532 /workspace/repository \
    && chmod -R a+rwX /workspace/repository
ENV NODE_OPTIONS=--openssl-legacy-provider
USER 65532
WORKDIR /workspace/repository
# Offline build: npm run build
