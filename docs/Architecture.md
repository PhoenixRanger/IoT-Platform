# Architecture

## Data flow

```text
ESP32 / Heltec firmware
  ├─ MQTT `sensors/<device_id>/readings` (normal)
  └─ HTTP `/api/data` (debug fallback)
             ↓
MQTT subscriber / Flask ingestion
             ↓
normalized SQLite nodes, sensors, measurements
             ↓
Flask APIs → dashboard and node-details page
```

MQTT keeps its flat, backward-compatible payload. The subscriber separates known string identity metadata from numeric readings. Metadata updates the existing `nodes` record; RSSI and uptime remain historical measurements. Online/offline is derived from the latest measurement rather than stored.

`init_db()` performs an idempotent in-place migration, adding nullable hardware model/revision, firmware name/version, and OTA hostname columns. Existing databases and automatically registered nodes remain valid.

## Firmware

The monorepo contains two independent PlatformIO projects: `environment-node` for the AZ-Delivery ESP32 DevKitC V2/DHT22 and `irrigation-controller` for the Heltec V3 dual-climate node. Only connection, metadata, OTA, and identity helpers are shared. Sensor/application code remains local to each project.

Each family has independent SemVer sourced from its `VERSION` file. Both formal histories begin at v1.0.0. A PlatformIO pre-build script exposes that value as `FIRMWARE_VERSION`.

Authenticated ArduinoOTA is serviced continuously while connected. `min_spiffs.csv` provides an OTA-capable partition layout. USB remains bootstrap and recovery; there is no browser update, fleet automation, FUOTA, signing, or secure boot in v1.10.1.
