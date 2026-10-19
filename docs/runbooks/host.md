# eris host

Alerts: `HostRootDiskAlmostFull`, `HostRootDiskFull`, `HostDiskWillFillIn24h`, `HostOutOfMemory`,
`HostHighCpuLoad`, `HostRebooted`, `GpuHot`, `GpuMemoryNearlyFull`.

## Disk full

```sh
df -h /
sudo du -xh --max-depth=1 /home/jeff/volumes | sort -h | tail
docker system df
```

Safe to reclaim:

```sh
docker image prune -a -f --filter until=168h     # unused images older than a week
docker builder prune -f
sudo journalctl --vacuum-size=500M
```

**Not** `docker system prune` / `docker container prune`: they delete the job containers.
Usual growers: `volumes/ollama` (models: `docker exec ollama ollama rm <model>`),
`volumes/monitor/prometheus`, `volumes/photon`, container logs (capped at 3×20 MB each by
`/etc/docker/daemon.json`).

## Memory / CPU

```sh
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' | sort -k3 -h | tail
```

Usual suspects: Ollama or Immich ML holding a model, the Immich/Photon importers, a game
server. `docker restart <name>` frees it.

## GPU

```sh
nvidia-smi
```

If `nvidia-smi` errors after a kernel update ("couldn't communicate with the driver"),
the driver didn't build for the new kernel: reboot once; if it persists,
`sudo apt install --reinstall nvidia-dkms-<version>` (version from `dpkg -l | grep nvidia-dkms`).
Containers using the GPU: ollama, whisper, immich ML (both), lora-studio.

## Rebooting eris (planned)

1. `bin/health`. Don't reboot while borgmatic runs (02:00–02:15) or while a NAS disk operation runs.
2. `sudo apt update && sudo apt full-upgrade` (optional), then `sudo reboot`.
3. At boot, `nas-wait.service` holds Docker for up to 5 minutes until the NAS shares mount.
   Containers come back by their restart policy.
4. After ~5 minutes: `bin/health`. If `InfraContainerGone` fires but everything is up,
   it's the cAdvisor boot race: `docker restart cadvisor`.

## eris won't boot / is unreachable

Plug in a monitor. If the disk or OS is gone, see [disaster-recovery.md](disaster-recovery.md).
While eris is down: **LAN DNS goes down too** (the router points at AdGuard on eris).
Set the router's DNS to `1.1.1.1` so the household keeps internet.
