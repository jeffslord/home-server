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

## What eris exposes (reviewed 2026-10-19)

Ports Docker publishes **bypass ufw**, so this list (and the router) is the real firewall.

| Port | Service | Reachable from |
|---|---|---|
| 443 tcp/udp | Caddy | Internet (router forward) |
| 53 tcp/udp | AdGuard DNS | LAN |
| 80 | AdGuard admin (own login) | LAN |
| 8123 | Home Assistant (Cast devices fetch media from it) | LAN |
| 9999 | Stash (its own login; not behind Authentik) | LAN |
| game ports | Minecraft 25565/25591, Palworld 8211/27015, Space Engineers 27016, Vintage Story 42420 (+42425, purpose unknown: don't forward) | Internet, only while a server runs |
| 1883 | Mosquitto | localhost only (wol-relay) |

Everything else is `127.0.0.1` or not published, and is reached through Caddy + Authentik.
Check the list against reality:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}' | grep -E '0\.0\.0\.0|\[::\]'
```

**Router check (do yearly or after router changes):** the router's port-forwarding page should
forward to 192.168.1.162 only 443 (tcp+udp) and the game ports above. Nothing else, especially
not 80, 8123, 9999, 53 or 22.
