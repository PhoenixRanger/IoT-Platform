# Operations Guide

## Routine checks

```bash
systemctl status iot-dashboard iot-mqtt-subscriber mosquitto
journalctl -u iot-mqtt-subscriber -n 50
mosquitto_sub -h localhost -t 'sensors/+/readings' -v
```

Open the dashboard, select the relevant node, and click its status tile to open the node-details page.

Confirm:

- online/offline status
- last seen
- RSSI
- uptime
- hardware model and revision
- firmware name and version
- OTA hostname

Unknown firmware or hardware metadata is expected on nodes that have not yet received the v1.10 OTA-capable firmware.

## Normal firmware update

After the initial USB bootstrap, routine firmware updates should not require physical access to the node.

If working remotely, first SSH into the property server. Then:

```bash
cd /home/iot/iot-dashboard
git pull
cd firmware/irrigation-controller
export OTA_PASSWORD='configured-secret'
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

The final PlatformIO command builds the current firmware if required and then transfers it to the node over Wi-Fi.

A separate:

```bash
pio run -e ota
```

build step is therefore not required for routine updates.

### Irrigation controller

```text
Firmware family: irrigation-controller
Node ID: irrigation_controller_001
OTA hostname: irrigation-controller-001.local
```

### Environmental node

```text
Firmware family: environment-node
Node ID: environment_node_001
OTA hostname: environment-node-001.local
```

A stable LAN IP or DHCP reservation is recommended for unattended remote updates because `.local` mDNS resolution may occasionally fail.

For example:

```bash
pio run -e ota -t upload --upload-port <node-ip-or-hostname>
```

Do not commit transient node IP addresses into firmware source.

## After an OTA update

The node should reboot automatically after a successful OTA upload.

Verify that:

1. the node returns to `online`
2. MQTT readings resume
3. RSSI updates
4. uptime restarts and continues increasing
5. expected sensor readings return
6. `/nodes/<node_id>` shows the expected firmware information

If the firmware version was intentionally changed, verify that the new version is reported by the node metadata.

## OTA password

The OTA password embedded in:

```text
include/secrets.h
```

must match the password supplied to PlatformIO through the terminal environment:

```bash
export OTA_PASSWORD='configured-secret'
```

If OTA authentication fails, verify that these two values match.

Changing only `include/secrets.h` does not change the password on an already-running node. The new password takes effect only after firmware containing that value has actually been flashed to the node.

PlatformIO or `espota.py` diagnostic output may display the authentication value. Do not share unredacted OTA logs containing the password.

## Rotating the OTA password

Change the password in the firmware family's local:

```text
include/secrets.h
```

Then update the current terminal environment:

```bash
unset OTA_PASSWORD
export OTA_PASSWORD='new-configured-secret'
```

Build the firmware:

```bash
pio run -e usb
```

If the currently installed node still uses the old password, either perform a USB flash or perform one final OTA upload authenticated with the old password while flashing firmware containing the new password.

After the node is running firmware containing the new password, export the new password and perform a final OTA test.

## OTA recovery

If Wi-Fi, authentication, firmware startup, or OTA becomes unusable, connect the board over USB.

Identify the serial port:

```bash
ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
```

Then recover the firmware:

```bash
cd /home/iot/iot-dashboard/firmware/<firmware-family>
pio run -e usb -t upload --upload-port /dev/ttyUSB0
```

Adjust `/dev/ttyUSB0` if necessary.

After recovery:

1. verify Wi-Fi connectivity
2. verify MQTT connectivity
3. verify node metadata
4. verify sensor operation
5. perform a local OTA test before relying on remote OTA again

USB remains the recovery path even though normal firmware maintenance is performed over OTA.

## Server service recovery

Check the services:

```bash
systemctl status mosquitto iot-dashboard iot-mqtt-subscriber
```

Restart them if required:

```bash
sudo systemctl restart mosquitto
sudo systemctl restart iot-dashboard
sudo systemctl restart iot-mqtt-subscriber
```

Inspect logs:

```bash
journalctl -u iot-dashboard -n 100
journalctl -u iot-mqtt-subscriber -n 100
```

Database backup/recovery and the established systemd procedures remain unchanged.

## MQTT testing

Use the Mosquitto command-line tools to verify the MQTT path independently of the ESP32 firmware.

In one terminal:

```bash
mosquitto_sub -h localhost -t 'sensors/+/readings' -v
```

In another terminal, publish a known-good test payload:

```bash
mosquitto_pub -h localhost -t sensors/environment_node_001/readings -m '{"device_id":"environment_node_001","temperature":25.5,"humidity":55,"rssi":-62,"uptime_seconds":1234}'
```

A healthy system should show the published topic and JSON payload in the subscriber terminal.

The MQTT subscriber service should then write the readings into the same SQLite database used by the Flask dashboard.

## Database backup

Back up `sensor.db` before upgrades, manual database work, or any maintenance where collected measurements should be protected.

From the project root:

```bash
cd /home/iot/iot-dashboard
scripts/backup_db.sh
```

The backup script writes timestamped copies into:

```text
backups/
```

Existing backups are not overwritten.

To back up a database at a custom path:

```bash
scripts/backup_db.sh /home/iot/iot-dashboard/sensor.db
```

## Database restore

Stop services that access the database:

```bash
sudo systemctl stop iot-mqtt-subscriber
sudo systemctl stop iot-dashboard
```

Move the current database aside:

```bash
mv sensor.db sensor.db.before_restore
```

Copy the selected backup into place:

```bash
cp backups/sensor_YYYYMMDD_HHMMSS.db sensor.db
```

Restart the services:

```bash
sudo systemctl start iot-dashboard
sudo systemctl start iot-mqtt-subscriber
```

Then verify the dashboard and recent measurements.

Do not replace `sensor.db` while the dashboard or MQTT subscriber is actively writing to it.

## Troubleshooting data flow

### Dashboard unavailable

Check:

```bash
systemctl status iot-dashboard
```

Restart if necessary:

```bash
sudo systemctl restart iot-dashboard
```

Then inspect:

```bash
journalctl -u iot-dashboard -n 100
```

### MQTT connection refused

Check Mosquitto:

```bash
systemctl status mosquitto
```

Restart if necessary:

```bash
sudo systemctl restart mosquitto
```

Then confirm the subscriber reconnects:

```bash
journalctl -u iot-mqtt-subscriber -f
```

### Subscriber not writing measurements

Inspect subscriber logs:

```bash
journalctl -u iot-mqtt-subscriber -n 100
```

Look for:

- payload validation failures
- database errors
- repeated broker reconnects
- malformed JSON
- unsupported sensor fields

Then publish a known-good MQTT test payload using the procedure above.

### Node is online but dashboard readings are stale

Check the path in this order:

1. verify the node is powered and connected to Wi-Fi
2. verify Mosquitto receives the node payload
3. verify the MQTT subscriber receives and stores it
4. verify the dashboard is reading the expected node
5. verify the browser is refreshing normally

Use:

```bash
mosquitto_sub -h localhost -t 'sensors/+/readings' -v
```

and:

```bash
journalctl -u iot-mqtt-subscriber -f
```

to identify where the data flow stops.

## Reboot verification checklist

After rebooting the Raspberry Pi or server, verify:

- [ ] Mosquitto is running
- [ ] `iot-mqtt-subscriber` is running
- [ ] `iot-dashboard` is running
- [ ] ESP32 nodes reconnect to Wi-Fi
- [ ] MQTT payloads arrive
- [ ] subscriber logs show successful database inserts
- [ ] dashboard values update
- [ ] node status is correct
- [ ] node metadata is available for OTA-capable nodes

Useful commands:

```bash
systemctl status mosquitto iot-mqtt-subscriber iot-dashboard
mosquitto_sub -h localhost -t 'sensors/+/readings' -v
journalctl -u iot-mqtt-subscriber -n 50
```
