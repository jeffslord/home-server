# Pinned: a floating `caddy:2-builder` silently picks up whatever caddy-dns/cloudflare
# is current at build time. The 13-month-old build rejected Cloudflare's newer
# `cfat_` token format outright and Caddy crash-looped on the next recreate.
# Bump deliberately, rebuild, and validate with `caddy validate` before `up -d`.
ARG CADDY_VERSION=2.11.4

FROM caddy:${CADDY_VERSION}-builder AS builder

RUN xcaddy build \
    --with github.com/caddy-dns/cloudflare \
    --with github.com/greenpau/caddy-security

FROM caddy:${CADDY_VERSION}

COPY --from=builder /usr/bin/caddy /usr/bin/caddy
