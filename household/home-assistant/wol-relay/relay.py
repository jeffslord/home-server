"""Wake-on-LAN relay for Home Assistant.

HA runs on the `web` Docker bridge, where a magic-packet broadcast never reaches
the LAN (Linux doesn't forward directed broadcasts). This runs with host
networking instead. It announces, per target, an MQTT "Wake" button and an
"Online" connectivity sensor through HA discovery; pressing the button sends the
magic packet to the LAN broadcast address.

TARGETS (env): semicolon-separated `id|Name|aa:bb:cc:dd:ee:ff|ip`.
"""
import json
import os
import socket
import threading
import time

import paho.mqtt.client as mqtt

BROADCAST = os.environ.get("BROADCAST", "192.168.1.255")
PROBE_PORTS = (445, 135, 3389, 22)  # any open port means the machine is up
PROBE_EVERY = 30

TARGETS = []
for spec in os.environ["TARGETS"].split(";"):
    tid, name, mac, ip = (s.strip() for s in spec.split("|"))
    TARGETS.append({"id": tid, "name": name, "mac": mac.lower().replace("-", ":"), "ip": ip})

AVAIL = "wol/relay/status"


def magic_packet(mac):
    raw = bytes.fromhex(mac.replace(":", ""))
    return b"\xff" * 6 + raw * 16


def wake(t):
    pkt = magic_packet(t["mac"])
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for _ in range(3):
            for addr in (BROADCAST, "255.255.255.255"):
                s.sendto(pkt, (addr, 9))
            time.sleep(0.2)
    print(f"sent magic packet to {t['name']} ({t['mac']})", flush=True)


def is_up(ip):
    for port in PROBE_PORTS:
        try:
            with socket.create_connection((ip, port), timeout=1):
                return True
        except OSError:
            continue
    return False


def announce(client):
    for t in TARGETS:
        device = {"identifiers": [f"wol_{t['id']}"], "name": t["name"],
                  "connections": [["mac", t["mac"]]]}
        common = {"availability_topic": AVAIL, "device": device}
        client.publish(f"homeassistant/button/wol_{t['id']}/config", json.dumps({
            **common, "name": "Wake", "unique_id": f"wol_{t['id']}_wake",
            "command_topic": f"wol/{t['id']}/wake", "icon": "mdi:power"}), retain=True)
        client.publish(f"homeassistant/binary_sensor/wol_{t['id']}/config", json.dumps({
            **common, "name": "Online", "unique_id": f"wol_{t['id']}_online",
            "device_class": "connectivity", "state_topic": f"wol/{t['id']}/state"}), retain=True)
        client.subscribe(f"wol/{t['id']}/wake")


def on_connect(client, userdata, flags, reason_code, properties):
    print(f"connected to MQTT ({reason_code})", flush=True)
    client.publish(AVAIL, "online", retain=True)
    announce(client)


def on_message(client, userdata, msg):
    for t in TARGETS:
        if msg.topic == f"wol/{t['id']}/wake":
            wake(t)


def probe_loop(client):
    while True:
        for t in TARGETS:
            client.publish(f"wol/{t['id']}/state", "ON" if is_up(t["ip"]) else "OFF", retain=True)
        time.sleep(PROBE_EVERY)


client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="wol-relay")
client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
client.will_set(AVAIL, "offline", retain=True)
client.on_connect = on_connect
client.on_message = on_message
client.connect(os.environ.get("MQTT_HOST", "127.0.0.1"), int(os.environ.get("MQTT_PORT", "1883")))
threading.Thread(target=probe_loop, args=(client,), daemon=True).start()
client.loop_forever()
