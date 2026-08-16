# Architecture

## Data flow

```text
ESP32 / Heltec firmware
  ├─ MQTT `sensors/<device_id>/readings` (normal)
  └─ HTTP `/api/data` (debug fallback)
             ↓
MQTT subscriber / Flask ingestion
             ↓
normalized SQLite nodes, sensors, measurements, capabilities
             ↓
Flask APIs → dashboard and node-details page
```

MQTT keeps its flat, backward-compatible payload. The subscriber separates device-owned metadata from numeric readings. Devices may update legacy `node_type`, hardware, firmware, and OTA hostname fields, while registry name, location, category, GPS, and enabled state remain server-owned. RSSI and uptime remain historical measurements. Online/offline is derived from the latest measurement rather than stored; disabled is an administrative override and does not block ingestion.

`init_db()` performs an idempotent in-place migration, adding nullable hardware model/revision, firmware name/version, OTA hostname, category, latitude, longitude, and an enabled flag that defaults true. Existing databases and automatically registered nodes remain valid.

Recent readings use `idx_measurements_node_timestamp_id` on `(node_id, timestamp DESC, id DESC)`. The first query walks this covering index only until it has found `READING_LIMIT` distinct recent timestamps in application code. A second indexed `IN` lookup retrieves every measurement at those timestamps in chronological order. Work is therefore driven by one node's requested recent cycles and their dynamic sensor rows, rather than a full-history grouping scan or a fixed sensor-count multiplier.

## Firmware

The monorepo contains two independent PlatformIO projects: `environment-node` for the AZ-Delivery ESP32 DevKitC V2/DHT22 and `irrigation-controller` for the Heltec V3 dual-climate node. Only connection, metadata, OTA, and identity helpers are shared. Sensor/application code remains local to each project.

Each family has independent SemVer sourced from its `VERSION` file. Both formal histories begin at v1.0.0. A PlatformIO pre-build script exposes that value as `FIRMWARE_VERSION`.

Authenticated ArduinoOTA is serviced continuously while connected. `min_spiffs.csv` provides an OTA-capable partition layout. USB remains bootstrap and recovery; there is no browser update, fleet automation, FUOTA, signing, or secure boot in v1.12.0.


## Generic capabilities

The system-owned `capabilities` registry defines stable functional keys classified as sensor, actuator, or communication. `node_expected_capabilities` stores operator-managed desired associations; `node_reported_capabilities` stores device-owned associations and `node_capability_reports` records the latest complete report even when it is empty. These tables are independent of node category, firmware family, and future physical component or pin models.

Firmware publishes a complete `capabilities` array as a metadata-only message on startup and each MQTT reconnect. The subscriber validates every key before atomically replacing the reported set. An unknown key rejects the entire report and preserves the prior set. Legacy reading messages without capabilities remain unchanged.

Capability state is `unknown` before any report, `capability_mismatch` when a reported set omits an expected key, and otherwise `healthy`; extra reported functions are informational. Overall health applies disabled, offline, and unknown runtime precedence before this capability state.
