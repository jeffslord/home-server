# The official image is opencode + ripgrep on Alpine and nothing else: no git,
# no node, no python. The agent's shell tool is useless for real repos without
# them. This adds the common toolchain; add more here as projects need it.
ARG OPENCODE_VERSION=latest
FROM ghcr.io/anomalyco/opencode:${OPENCODE_VERSION}

RUN apk add --no-cache \
      bash git curl jq \
      python3 py3-pip \
      nodejs npm \
      make gcc musl-dev

# Entrypoint is reset so compose can wrap it in a shell for the secret export.
ENTRYPOINT []
