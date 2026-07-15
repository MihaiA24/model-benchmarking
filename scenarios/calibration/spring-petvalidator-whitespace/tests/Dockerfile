FROM maven:3.9.11-eclipse-temurin-21@sha256:6fdc855a6ed81d288ca7ca37ac6ff5e9308b612485c0801d70b25a858c83d237
USER root
COPY . /tests/
RUN --network=none chmod +x /tests/test.sh
USER 65532
WORKDIR /workspace/repository
# Example test: mvn -q test
