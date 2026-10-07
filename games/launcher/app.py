"""Game server launcher: lets players start stopped game servers from a web
page, and stops servers that have had no players for IDLE_MINUTES.

Stdlib only. Talks to Docker through socket-proxy, which only allows
listing/inspecting containers and start/stop (see docker-compose.yaml).
"""
import hashlib
import hmac
import http.cookies
import json
import logging
import os
import re
import socket
import statistics
import struct
import threading
import time
import urllib.error
import urllib.request
import zipfile
from base64 import b64encode
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DOCKER = os.environ.get("DOCKER_HOST_URL", "http://socket-proxy:2375")
IDLE_SECONDS = int(os.environ.get("IDLE_MINUTES", "30")) * 60
POLL_SECONDS = 15
CONNECT_HOST = os.environ.get("CONNECT_HOST", "")
PASSWORD = Path("/run/secrets/launcher_password").read_text().strip()
COOKIE = "launcher"
COOKIE_VALUE = hmac.new(PASSWORD.encode(), b"launcher-session", hashlib.sha256).hexdigest()
INDEX_HTML = (Path(__file__).parent / "index.html").read_bytes()
STATE_FILE = Path("/data/state.json")  # boot times + last known versions
VS_DATA = Path("/vintagestory")  # the Vintage Story data dir, read-only

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("launcher")


# --- Palworld ---------------------------------------------------------------

def palworld_api(path):
    req = urllib.request.Request(f"http://palworld:8212/v1/api/{path}")
    auth = b64encode(f"admin:{os.environ['PALWORLD_ADMIN_PASSWORD']}".encode()).decode()
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r)


def palworld_query():
    players = len(palworld_api("players")["players"])
    return players, palworld_api("info")["version"]


def palworld_details():
    return [{"label": "Password", "value": os.environ.get("PALWORLD_SERVER_PASSWORD", ""), "copy": True}]


# --- Vintage Story ----------------------------------------------------------

def _rcon(host, port, password, command):
    """Source RCON. VintageRCon answers the command with packet id 2."""
    with socket.create_connection((host, port), timeout=5) as s:
        def send(pid, ptype, body):
            payload = struct.pack("<ii", pid, ptype) + body.encode() + b"\0\0"
            s.sendall(struct.pack("<i", len(payload)) + payload)

        def recv():
            size = struct.unpack("<i", s.recv(4))[0]
            data = b""
            while len(data) < size:
                chunk = s.recv(size - len(data))
                if not chunk:
                    raise ConnectionError("rcon closed")
                data += chunk
            pid, _ = struct.unpack("<ii", data[:8])
            return pid, data[8:-2].decode(errors="replace")

        send(1, 3, password)
        send(2, 2, command)
        while True:
            pid, body = recv()
            if pid == -1:
                raise PermissionError("rcon auth failed")
            if pid == 2:
                return body


def vs_rcon(command):
    password = json.loads((VS_DATA / "ModConfig/vsrcon.json").read_text())["Password"]
    return _rcon("vintagestory", 42425, password, command)


def vintagestory_query():
    # "List of online Players\n" then one line per player.
    body = vs_rcon("list clients")
    return len([l for l in body.splitlines()[1:] if l.strip()]), None


def vintagestory_save():
    vs_rcon("autosavenow")
    time.sleep(15)  # the save runs off-thread; give it time to finish


def vintagestory_version():
    try:
        with open(VS_DATA / "Logs/server-main.log", errors="replace") as f:
            for line in f:
                if m := re.search(r"Game Version: (v\S+)", line):
                    return m.group(1)
    except OSError:
        pass
    return None


def vintagestory_details():
    password = json.loads((VS_DATA / "serverconfig.json").read_text()).get("Password")
    return [{"label": "Password", "value": password, "copy": True}] if password else []


def _lenient_json(raw):
    # modinfo.json is hand-written: allow trailing commas.
    return json.loads(re.sub(r",\s*([}\]])", r"\1", raw))


def vintagestory_mods():
    """Mods players need (everything not marked server-only), from each zip's modinfo.json."""
    mods = []
    for path in sorted((VS_DATA / "Mods").glob("*.zip")):
        info = {}
        try:
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.lower() == "modinfo.json"), None)
                if name:
                    info = {k.lower(): v for k, v in _lenient_json(z.read(name).decode("utf-8-sig")).items()}
        except (zipfile.BadZipFile, ValueError, OSError) as e:
            log.warning("mod %s: %s", path.name, e)
        side = str(info.get("side", "universal")).lower()
        if side == "server":
            continue
        mods.append({
            "name": info.get("name") or path.stem,
            "version": info.get("version"),
            "optional": side == "client",
            "file": path.name,
        })
    return sorted(mods, key=lambda m: m["name"].lower())


# --- Space Engineers --------------------------------------------------------

def a2s_info(host, port):
    """Steam A2S_INFO query -> (server name, map/world, players, raw reply)."""
    req = b"\xff\xff\xff\xffTSource Engine Query\x00"
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(3)
        s.sendto(req, (host, port))
        data, _ = s.recvfrom(1400)
        if data[4:5] == b"A":  # challenge
            s.sendto(req + data[5:9], (host, port))
            data, _ = s.recvfrom(1400)
    if data[4:5] != b"I":
        raise ValueError("unexpected A2S reply")
    fields, pos = [], 6
    for _ in range(4):  # name, map, folder, game
        end = data.index(b"\0", pos)
        fields.append(data[pos:end].decode(errors="replace"))
        pos = end + 1
    return fields[0], fields[1], data[pos + 2], data


def space_engineers_query():
    name, world, players, raw = a2s_info("space-engineers", 27016)
    version = None
    if m := re.search(rb"version(\d)(\d{3})(\d{3})", raw):  # 1209024 -> 1.209.024
        version = ".".join(g.decode() for g in m.groups())
    with lock:
        state["se_names"] = [name, world]
    return players, version


SE_CONTROL = Path("/se-control")  # watched by the SaveAndStop plugin (games/space-engineers/save-and-stop-plugin)


def space_engineers_save():
    """Ask the plugin to save; it then exits the server itself. Waits for the save."""
    status_file = SE_CONTROL / "status"
    status_file.unlink(missing_ok=True)
    (SE_CONTROL / "save-and-stop").touch()
    deadline = time.time() + 180
    while time.time() < deadline:
        if status_file.exists():
            result = status_file.read_text().strip()
            if result != "saved":
                raise RuntimeError(f"plugin reported {result}")
            return
        time.sleep(1)
    (SE_CONTROL / "save-and-stop").unlink(missing_ok=True)
    raise TimeoutError("no answer from SaveAndStop plugin")


def space_engineers_details():
    names = state.get("se_names")
    if not names:
        return []
    return [{"label": "Server name", "value": names[0], "copy": True},
            {"label": "World", "value": names[1]}]


GAMES = {
    "palworld": {
        "name": "Palworld",
        "container": "palworld",
        "port": 8211,
        "query": palworld_query,
        "details": palworld_details,
        "stop_timeout": 60,  # image saves via its REST API on SIGTERM
        "howto": "In Palworld: Join Multiplayer Game, paste the address at the bottom, then enter the password.",
    },
    "vintagestory": {
        "name": "Vintage Story",
        "container": "vintagestory",
        "port": 42420,
        "query": vintagestory_query,
        "details": vintagestory_details,
        "version": vintagestory_version,
        "mods": vintagestory_mods,
        "before_stop": vintagestory_save,
        "stop_timeout": 60,
        "howto": "In Vintage Story: Multiplayer, Add Server, paste the address. "
                 "You need the same game version and the mods below.",
    },
    "space-engineers": {
        "name": "Space Engineers",
        "container": "space-engineers",
        "port": 27016,
        "query": space_engineers_query,
        "details": space_engineers_details,
        # Under Wine it ignores SIGTERM, so the plugin saves and exits it; the
        # docker stop right after keeps restart: unless-stopped from rebooting it.
        "before_stop": space_engineers_save,
        "stop_timeout": 30,
        "howto": "In Space Engineers: Join Game, Servers tab, search for the server name.",
    },
}


# --- Persistent state -------------------------------------------------------

lock = threading.Lock()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, ValueError):
        return {}


def save_state():
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE_FILE)


state = load_state()
state.setdefault("boot_seconds", {})  # gid -> last 5 measured boots
state.setdefault("versions", {})      # gid -> last version the server reported


def boot_estimate(gid):
    times = state["boot_seconds"].get(gid)
    return int(statistics.median(times)) if times else None


# --- Docker -----------------------------------------------------------------

def docker(method, path):
    req = urllib.request.Request(DOCKER + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            body = r.read()
            return json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        if e.code == 304:  # already started/stopped
            return None
        raise


def inspect(container):
    s = docker("GET", f"/containers/{container}/json")["State"]
    started = datetime.fromisoformat(s["StartedAt"][:26].rstrip("Z") + "+00:00").timestamp()
    return s["Running"], (s.get("Health") or {}).get("Status"), started


# --- Idle watcher -----------------------------------------------------------

status = {gid: {"state": "unknown", "players": None, "idle_since": None, "busy": None,
                "started_at": None, "saw_boot": False} for gid in GAMES}


def refresh(gid):
    game, st = GAMES[gid], status[gid]
    try:
        running, health, started_at = inspect(game["container"])
    except Exception as e:
        log.warning("%s: docker inspect failed: %s", gid, e)
        return
    players = version = None
    if running and health != "starting":
        try:
            players, version = game["query"]()
        except Exception as e:
            log.debug("%s: query failed: %s", gid, e)
    now = time.time()
    with lock:
        if running and players is None and st["state"] == "running" and st["started_at"] == started_at:
            # A missed query on a server that was already up: keep the last
            # count and idle clock rather than treating it as a new boot.
            players = st["players"]
        if not running:
            new_state = "stopped"
        elif players is None:
            # Up, but not answering yet: booting (or wedged; the page says so if it runs long).
            new_state = "starting"
        else:
            new_state = "running"

        if new_state == "starting" and st["started_at"] != started_at:
            st["saw_boot"] = True  # only time boots we watched from the start
        if new_state == "running" and st["state"] == "starting" and st["saw_boot"]:
            took = int(now - started_at)
            if 0 < took < 3600:
                times = state["boot_seconds"].setdefault(gid, [])
                times[:] = (times + [took])[-5:]
                log.info("%s: ready after %ds", gid, took)
            st["saw_boot"] = False
        if version:
            state["versions"][gid] = version

        st["state"], st["players"] = new_state, players
        st["started_at"] = started_at if running else None
        if new_state != "running" or players != 0:
            st["idle_since"] = None  # stopped, booting, unreachable, or someone is on
        elif st["idle_since"] is None:
            st["idle_since"] = now
        save_state()


def stop(gid, reason):
    game, st = GAMES[gid], status[gid]
    with lock:
        if st["busy"]:
            return
        st["busy"] = "stopping"
    try:
        log.info("%s: stopping (%s)", gid, reason)
        if "before_stop" in game:
            try:
                game["before_stop"]()
            except Exception as e:
                log.warning("%s: pre-stop save failed: %s", gid, e)
        docker("POST", f"/containers/{game['container']}/stop?t={game['stop_timeout']}")
        log.info("%s: stopped", gid)
    finally:
        with lock:
            st["busy"] = None
        refresh(gid)


def start(gid):
    game, st = GAMES[gid], status[gid]
    refresh(gid)  # it may have been stopped/started outside the launcher
    with lock:
        if st["busy"] or st["state"] != "stopped":
            return False
        st["busy"] = "starting"
    try:
        log.info("%s: starting", gid)
        docker("POST", f"/containers/{game['container']}/start")
    finally:
        with lock:
            st["busy"] = None
        refresh(gid)
    return True


def watcher():
    while True:
        for gid in GAMES:
            refresh(gid)
            with lock:
                idle_since = status[gid]["idle_since"]
            if idle_since and time.time() - idle_since >= IDLE_SECONDS:
                threading.Thread(target=stop, args=(gid, "idle"), daemon=True).start()
        time.sleep(POLL_SECONDS)


def game_status(gid, now):
    g, st = GAMES[gid], status[gid]
    try:
        details = g["details"]()
    except Exception as e:
        log.warning("%s: details failed: %s", gid, e)
        details = []
    version = g["version"]() if "version" in g else state["versions"].get(gid)
    if version:
        details.append({"label": "Version", "value": version})
    return {
        "id": gid,
        "name": g["name"],
        "address": f"{CONNECT_HOST}:{g['port']}" if CONNECT_HOST else None,
        "state": st["busy"] or st["state"],
        "players": st["players"],
        "stops_in": max(0, int(IDLE_SECONDS - (now - st["idle_since"]))) if st["idle_since"] else None,
        "boot_elapsed": int(now - st["started_at"]) if st["state"] == "starting" and st["started_at"] else None,
        "boot_estimate": boot_estimate(gid),
        "howto": g["howto"],
        "details": details,
        "has_mods": "mods" in g,
    }


# --- Web --------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def authed(self):
        c = http.cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return COOKIE in c and hmac.compare_digest(c[COOKIE].value, COOKIE_VALUE)

    def send(self, code, body=b"", ctype="application/json", headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, INDEX_HTML, "text/html; charset=utf-8")
        if self.path == "/healthz":
            return self.send(200, {"ok": True})
        if not self.path.startswith(("/api/", "/download/")):
            return self.send(404, {"error": "not found"})
        if not self.authed():
            return self.send(401, {"error": "login"})
        if self.path == "/api/status":
            now = time.time()
            with lock:
                games = [game_status(gid, now) for gid in GAMES]
            return self.send(200, {"games": games, "idle_minutes": IDLE_SECONDS // 60})
        if m := re.fullmatch(r"/api/mods/([\w-]+)", self.path):
            if "mods" not in GAMES.get(m.group(1), {}):
                return self.send(404, {"error": "no mods"})
            mods = GAMES[m.group(1)]["mods"]()
            return self.send(200, [{k: v for k, v in mod.items() if k != "file"} for mod in mods])
        if m := re.fullmatch(r"/download/([\w-]+)-mods\.zip", self.path):
            if "mods" not in GAMES.get(m.group(1), {}):
                return self.send(404, {"error": "no mods"})
            return self.send_mods_zip(m.group(1))
        self.send(404, {"error": "not found"})

    def send_mods_zip(self, gid):
        """Stream the mod zips players need, bundled into one (stored, they're already compressed)."""
        mods = GAMES[gid]["mods"]()
        self.send_response(200)
        self.send_header("Content-Type", "application/zip")
        self.send_header("Content-Disposition", f'attachment; filename="{gid}-mods.zip"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_STORED) as z:
            for mod in mods:
                z.write(VS_DATA / "Mods" / mod["file"], mod["file"])

    def do_POST(self):
        # Custom header forces a CORS preflight, so other sites can't POST here.
        if self.headers.get("X-Launcher") != "1":
            return self.send(400, {"error": "bad request"})
        if self.path == "/api/login":
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            try:
                pw = json.loads(self.rfile.read(length)).get("password", "")
            except ValueError:
                pw = ""
            if not hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                return self.send(401, {"error": "wrong password"})  # counted by fail2ban caddy-auth
            cookie = f"{COOKIE}={COOKIE_VALUE}; Max-Age={90 * 86400}; Path=/; HttpOnly; Secure; SameSite=Strict"
            return self.send(200, {"ok": True}, headers=[("Set-Cookie", cookie)])
        if self.path.startswith("/api/start/"):
            if not self.authed():
                return self.send(401, {"error": "login"})
            gid = self.path.removeprefix("/api/start/")
            if gid not in GAMES:
                return self.send(404, {"error": "unknown game"})
            threading.Thread(target=start, args=(gid,), daemon=True).start()
            return self.send(202, {"ok": True})
        self.send(404, {"error": "not found"})


if __name__ == "__main__":
    for gid in GAMES:
        refresh(gid)
    threading.Thread(target=watcher, daemon=True).start()
    log.info("listening on :8080, idle stop after %d min", IDLE_SECONDS // 60)
    ThreadingHTTPServer(("", 8080), Handler).serve_forever()
