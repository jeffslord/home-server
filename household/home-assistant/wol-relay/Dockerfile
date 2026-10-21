# Runtime for relay.py (Wake-on-LAN over MQTT). The script is bind-mounted, so the
# image only carries the dependency.
FROM python:3.12-slim
RUN pip install --no-cache-dir paho-mqtt==2.1.0
WORKDIR /app
CMD ["python", "-u", "relay.py"]
