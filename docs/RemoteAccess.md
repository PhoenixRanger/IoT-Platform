# Remote Access and OTA

Tailscale provides private remote SSH and dashboard access to the property server.

ESP32 nodes remain on the property's local Wi-Fi network and do not need to run Tailscale themselves.

The remote-access architecture is:

```text
Developer computer
        ↓
     Tailscale
        ↓
Property Raspberry Pi/server
        ↓
 Property LAN/Wi-Fi
        ↓
      ESP32
```

The property server acts as the bridge between remote development access and the locally connected ESP32 nodes.

## Remote server access

From the developer computer:

```bash
ssh <pi-user>@<pi-tailscale-name-or-ip>
```

After authentication, normal Linux terminal access to the property server is available.

The Raspberry Pi does not require Arduino IDE or a graphical desktop for firmware deployment. PlatformIO Core provides the required build and upload tools directly from the command line.

## Remote firmware update

After connecting to the property server over SSH:

```bash
cd /home/iot/iot-dashboard
git pull
cd firmware/irrigation-controller
export OTA_PASSWORD='configured-secret'
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

The property server builds the firmware and performs the final OTA upload over the property's local Wi-Fi network.

The ESP32 itself does not need direct Tailscale or Internet access.

### Irrigation controller

```text
Firmware family: irrigation-controller
Node ID: irrigation_controller_001
OTA hostname: irrigation-controller-001.local
```

Example:

```bash
cd /home/iot/iot-dashboard/firmware/irrigation-controller
export OTA_PASSWORD='configured-secret'
pio run -e ota -t upload --upload-port irrigation-controller-001.local
```

### Environmental node

```text
Firmware family: environment-node
Node ID: environment_node_001
OTA hostname: environment-node-001.local
```

Example:

```bash
cd /home/iot/iot-dashboard/firmware/environment-node
export OTA_PASSWORD='configured-secret'
pio run -e ota -t upload --upload-port environment-node-001.local
```

## Stable node addressing

mDNS `.local` hostnames may occasionally fail to resolve.

For reliable unattended remote deployment, a DHCP-reserved LAN IP is preferred.

For example:

```bash
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

The actual address should be confirmed on the property network and preferably reserved in the router before relying on it remotely.

Do not commit transient node IP addresses into firmware source.

## Normal remote deployment workflow

Once a node has received its initial OTA-capable firmware over USB, normal remote firmware maintenance becomes:

```text
Develop firmware
      ↓
Commit / merge to GitHub
      ↓
SSH to property server over Tailscale
      ↓
git pull
      ↓
PlatformIO OTA upload
      ↓
ESP32 receives firmware
      ↓
ESP32 reboots
      ↓
Verify node metadata and telemetry
```

In practical terms:

```bash
ssh <pi-user>@<pi-tailscale-name-or-ip>

cd /home/iot/iot-dashboard
git pull

cd firmware/<firmware-family>
export OTA_PASSWORD='configured-secret'

pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

No physical access, Arduino IDE, desktop environment, or USB connection is required during a normal OTA update.

## OTA authentication

The node's OTA password is stored locally in the ignored firmware file:

```text
include/secrets.h
```

The uploading shell must receive the same password through:

```bash
export OTA_PASSWORD='configured-secret'
```

Never commit the OTA password to Git.

PlatformIO uploader or debug output may expose the authentication value. Do not share unredacted OTA logs containing the password.

## Verification after remote update

After a successful OTA upload, verify through the dashboard that:

- the node returns online
- MQTT telemetry resumes
- RSSI is reported
- uptime restarts and continues increasing
- expected sensors resume reporting
- the node-details page reports the expected firmware version

A successful PlatformIO upload alone should not be treated as complete deployment verification.

## Recovery requirement

USB remains the recovery method if:

- Wi-Fi credentials are incorrect
- OTA authentication is broken
- firmware crashes before OTA starts
- network connectivity is lost
- an incompatible firmware image is deployed
- the node can no longer be reached over the LAN

Do not perform a high-risk remote firmware update on a critical unattended node unless physical USB recovery can eventually be provided.

See `Operations.md` for the USB recovery procedure and `Deployment.md` for initial PlatformIO and node setup.

## Remote access verification checklist

After setting up Tailscale, after rebooting the property server, or after changing networks, verify:

- [ ] property Raspberry Pi/server is powered and online
- [ ] Tailscale is running on the property server
- [ ] developer device is logged into the same tailnet
- [ ] remote SSH works
- [ ] dashboard loads over the Tailscale connection
- [ ] ESP32 nodes continue publishing over the local property Wi-Fi
- [ ] MQTT subscriber remains connected
- [ ] normal OTA target addresses are still reachable from the property server

## Tailscale troubleshooting

### Dashboard works locally but not over Tailscale

First verify the Flask service:

```bash
systemctl status iot-dashboard
```

If the local dashboard works but the Tailscale address does not, focus troubleshooting on:

- Tailscale status on the server
- Tailscale status on the developer device
- tailnet membership
- the server's current Tailscale IP or hostname

### SSH works locally but not over Tailscale

Confirm that the property server appears online in Tailscale.

Then retry:

```bash
ssh <pi-user>@<pi-tailscale-name-or-ip>
```

If local SSH works but remote SSH does not, the problem is likely in the Tailscale connection rather than the Linux SSH service.

### Property server does not appear in Tailscale

Check that the server:

- has Internet access
- has Tailscale installed
- is logged into the correct account or tailnet
- is running the Tailscale service

After reconnecting, verify the server appears online from the developer device.

### ESP32 readings are missing during remote access

Tailscale is not part of the ESP32-to-Pi MQTT path.

The local sensor path remains:

```text
ESP32
  ↓ local Wi-Fi
Mosquitto
  ↓
MQTT subscriber
  ↓
SQLite
  ↓
Flask dashboard
```

If ESP32 data is missing, check:

```bash
systemctl status mosquitto
systemctl status iot-mqtt-subscriber
mosquitto_sub -h localhost -t 'sensors/+/readings' -v
journalctl -u iot-mqtt-subscriber -f
```

Do not troubleshoot Tailscale first unless access to the Raspberry Pi itself is also failing.

## Local versus Tailscale troubleshooting

| Symptom | Most likely area |
| --- | --- |
| Local dashboard works, remote dashboard fails | Tailscale connectivity or remote address |
| Remote dashboard works, local dashboard fails | Local LAN addressing or Wi-Fi |
| Both dashboard paths fail | Flask service or property server availability |
| SSH works locally but not remotely | Tailscale connectivity |
| SSH fails locally and remotely | Property server or SSH service |
| Dashboard loads but sensor data is stale | ESP32 Wi-Fi, Mosquitto, subscriber, or SQLite |
| OTA hostname fails but node IP works | mDNS resolution |
| OTA fails by hostname and IP | node Wi-Fi, OTA service, authentication, or firmware |
