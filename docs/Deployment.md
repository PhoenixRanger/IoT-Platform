# Deployment Guide

## Server

```bash
cd /home/iot/iot-dashboard
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart iot-dashboard
sudo systemctl restart iot-mqtt-subscriber
```

The Flask and MQTT subscriber services retain their current commands (`python run.py` and `python -m app.mqtt_subscriber`). Both call the safe database initializer; the first start upgrades an older `sensor.db` in place.

Back up the database before deployment as normal.

## PlatformIO firmware prerequisite

PlatformIO Core is required on any machine that will build or upload firmware, including the Raspberry Pi used for remote OTA deployment.

On Raspberry Pi OS, install PlatformIO using the official installer rather than modifying the system Python environment:

```bash
cd ~
curl -fsSL -o get-platformio.py https://raw.githubusercontent.com/platformio/platformio-core-installer/master/get-platformio.py
python3 get-platformio.py
```

Expose the `pio` command:

```bash
mkdir -p ~/.local/bin
ln -sf ~/.platformio/penv/bin/pio ~/.local/bin/pio
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

Verify:

```bash
pio --version
```

The first PlatformIO build may take several minutes because the ESP32 platform, compiler toolchain, framework, and libraries are downloaded. Later builds reuse the local cache.

## Raspberry Pi ARM toolchain compatibility

On the current 32-bit Raspberry Pi OS `armhf` installation, PlatformIO's ESP32 toolchains may exist but fail with:

```text
cannot execute: required file not found
```

or:

```text
xtensa-esp32s3-elf-g++: not found
```

If the compiler exists and `file` shows that it expects `/lib/ld-linux.so.3`, while the Pi provides `/lib/ld-linux-armhf.so.3`, verify:

```bash
uname -m
dpkg --print-architecture
ls -l /lib/ld-linux*
```

For the tested `armhf` Raspberry Pi setup, the compatibility symlink is:

```bash
sudo ln -s /lib/ld-linux-armhf.so.3 /lib/ld-linux.so.3
```

Then verify the compiler directly, for example:

```bash
~/.platformio/packages/toolchain-xtensa-esp32s3/bin/xtensa-esp32s3-elf-g++ --version
```

Do not apply this workaround blindly on systems with a different architecture. It is only needed when the installed PlatformIO toolchain specifically expects `/lib/ld-linux.so.3`.

## Firmware secrets

Each firmware family uses a local ignored secrets file.

For the irrigation controller:

```bash
cd /home/iot/iot-dashboard/firmware/irrigation-controller
cp include/secrets.example.h include/secrets.h
nano include/secrets.h
```

For the environmental node:

```bash
cd /home/iot/iot-dashboard/firmware/environment-node
cp include/secrets.example.h include/secrets.h
nano include/secrets.h
```

Configure:

- Wi-Fi SSID
- Wi-Fi password
- MQTT broker LAN address
- OTA password
- unique node ID
- unique OTA hostname

> **Upgrading from v1.10.0:** Existing installations must add `NODE_ID` and `OTA_HOSTNAME` to their local `include/secrets.h` before building v1.10.1. Use the node's existing ID and OTA hostname to preserve MQTT topics, database identity, and OTA compatibility. Do not replace them with the generic example values unless you intentionally want to rename the deployed node.

`include/secrets.h` is ignored by Git and must never be committed.

The OTA password in `include/secrets.h` is compiled into the node firmware. During a later OTA upload, the `OTA_PASSWORD` environment variable on the uploading machine must contain the exact same value.

## Initial USB bootstrap

The first OTA-capable installation requires USB.

For the Heltec irrigation controller:

```bash
cd /home/iot/iot-dashboard/firmware/irrigation-controller
pio run -e usb
```

Identify the serial port:

```bash
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

Then upload, adjusting the port if necessary:

```bash
pio run -e usb -t upload --upload-port /dev/ttyUSB0
```

Optional serial monitoring:

```bash
pio device monitor --port /dev/ttyUSB0 --baud 115200
```

After bootstrap, verify that the node:

- joins Wi-Fi
- connects to MQTT
- publishes its sensor readings
- reports RSSI and uptime
- publishes hardware and firmware metadata
- starts authenticated OTA
- appears correctly on `/nodes/<node_id>`

The first OTA-enabled installation requires USB only once under normal operation. USB remains the recovery method if Wi-Fi or OTA is later broken.

Repeat the same process under `firmware/environment-node` for the original ESP32 desk node.

## Local OTA validation

Set the same OTA password used in `include/secrets.h`:

```bash
export OTA_PASSWORD='configured-secret'
```

Then upload directly over the local network:

```bash
cd /home/iot/iot-dashboard/firmware/irrigation-controller
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

The tested Heltec OTA hostname is:

```text
irrigation-controller-001.local
```

The environmental node uses:

```text
environment-node-001.local
```

mDNS `.local` resolution may be intermittent. A stable LAN IP or DHCP reservation is preferred for reliable remote operations.

For example:

```bash
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

Do not commit transient node IP addresses into firmware source.

## OTA credential safety

PlatformIO/`espota.py` diagnostic output may print the OTA password in command/debug output.

Do not paste or publish unredacted OTA upload logs containing the authentication value.

If an OTA password is exposed, rotate it in `include/secrets.h`, rebuild and USB-flash or OTA-flash the new firmware, then use the new value for future uploads.

## Existing systemd workflow

Keep the established service layout.

The dashboard service runs:

```text
/home/iot/iot-dashboard/venv/bin/python run.py
```

The subscriber service uses the same interpreter with:

```text
-m app.mqtt_subscriber
```

Both use `/home/iot/iot-dashboard` as their working directory. The examples use a generic dedicated service account named `iot`; adjust the account and paths consistently for the target host.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now mosquitto iot-dashboard iot-mqtt-subscriber
systemctl status mosquitto iot-dashboard iot-mqtt-subscriber
journalctl -u iot-dashboard -f
journalctl -u iot-mqtt-subscriber -f
```

## Mosquitto MQTT broker setup

Mosquitto runs on the Raspberry Pi as the local MQTT broker for Wi-Fi sensor nodes.

Install Mosquitto and its command-line clients:

```bash
sudo apt update
sudo apt install mosquitto mosquitto-clients
```

Create the local broker configuration file:

```text
/etc/mosquitto/conf.d/iot-dashboard.conf
```

For development or a trusted, firewalled LAN only, use:

```text
listener 1883 0.0.0.0
allow_anonymous true
```

This allows ESP32 nodes on the local property network to connect to the Raspberry Pi broker on port `1883`. It permits anonymous access on all interfaces and is **not a recommended production configuration**. Production deployments should require authenticated MQTT, restrict broker access with appropriate network controls and firewall rules, and apply stronger security appropriate to their threat model.

Enable and start Mosquitto:

```bash
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
systemctl status mosquitto
```

Follow Mosquitto logs:

```bash
journalctl -u mosquitto -f
```

## MQTT subscriber systemd service

The MQTT subscriber should run as a persistent systemd service.

Create:

```text
/etc/systemd/system/iot-mqtt-subscriber.service
```

with:

```ini
[Unit]
Description=IoT Dashboard MQTT Subscriber
After=network-online.target mosquitto.service
Wants=network-online.target
Requires=mosquitto.service

[Service]
WorkingDirectory=/home/iot/iot-dashboard
ExecStart=/home/iot/iot-dashboard/venv/bin/python -m app.mqtt_subscriber
Restart=always
RestartSec=5
User=iot

[Install]
WantedBy=multi-user.target
```

Then enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable iot-mqtt-subscriber
sudo systemctl start iot-mqtt-subscriber
systemctl status iot-mqtt-subscriber
```

Follow subscriber logs:

```bash
journalctl -u iot-mqtt-subscriber -f
```
