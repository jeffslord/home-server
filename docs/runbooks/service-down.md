# Websites and network

Alerts: `ServiceDown` (internal probe fails = the app is down), `EndpointDown` (app fine, public
route broken), `HostUnreachable`, `TlsCertExpiringSoon`, `SlowEndpoint`.

## Work out which layer is broken

A request goes: DNS (Cloudflare, or AdGuard on the LAN) → router port 443 → **Caddy** →
**Authentik** forward-auth → the app container.

```sh
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'caddy|authentik|<app>'
curl -sI https://<app>.jeffslord.com | head -3        # from eris
docker logs --tail 30 caddy
```

| Result | Layer | Fix |
|---|---|---|
| `ServiceDown` | The app | [containers.md](containers.md) |
| Every site down at once | Caddy or Authentik | `docker logs caddy`, `docker logs authentik-server`; `docker compose up -d` in `network/caddy` or `auth/` |
| Login loop / 500 after login | Authentik | `docker restart authentik-server authentik-worker`; check `authentik-postgresql` is healthy |
| Works on LAN, not outside | DNS / router / IP changed | `docker logs cloudflare-ddns`; compare `curl -s ifconfig.me` with `dig +short <app>.jeffslord.com @1.1.1.1` |
| `could not resolve` on the LAN | AdGuard | `docker restart adguardhome`; bypass: set router DNS to `1.1.1.1` |
| Cert error | ACME | `docker logs caddy 2>&1 \| grep -i acme`; usually the Cloudflare token (`_secrets/cloudflare_api_token.txt`) |

After editing the Caddyfile:

```sh
docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
docker exec caddy caddy reload   --config /etc/caddy/Caddyfile --adapter caddyfile
```

## `HostUnreachable`

| Instance | Meaning | Do |
|---|---|---|
| `192.168.1.1` | Router | Check the router; if eris itself lost network, see [host.md](host.md) |
| `192.168.1.172` | NAS | [nas.md](nas.md) |
| `1.1.1.1` | Internet | ISP outage; nothing to do on the server |

## Locked out by fail2ban

From the LAN:

```sh
docker exec fail2ban fail2ban-client status                 # list jails
docker exec fail2ban fail2ban-client set <jail> unbanip <ip>
```
