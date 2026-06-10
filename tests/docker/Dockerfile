# Minimal image providing a real `systemd-analyze` for integration tests.
FROM debian:trixie-slim
RUN apt-get update \
    && apt-get install -y --no-install-recommends systemd \
    && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["systemd-analyze"]
