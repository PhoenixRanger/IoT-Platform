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

The system-owned `capabilities` registry defines stable functional keys classified as sensor, actuator, or communication. Active `component_capability_instances` derive current Expected capability types and counts; legacy `node_expected_capabilities` rows remain storage/API compatibility data and do not influence current Node Management. `node_reported_capabilities` stores device-owned associations and `node_capability_reports` records the latest complete report even when it is empty. Reported state remains independent of physical inventory and future pin models.

Reusable component definitions and connected components both use lifecycle removal. Definitions use an internal integer relationship identity plus a hidden `definition_key`; stable seed keys remain for idempotency and custom keys are generated automatically. A physical module is stored in `connected_components` and owns the immutable public `connected_component_id` (`nc_…`). Each connected component owns one normalized capability instance for every currently provided generic capability, and only these children own `capability_instance_id` (`ci_…`). Expected counts derive from active capability instances.

The bounded v1.15 migration renames `node_component_instances.instance_id` to `connected_components.connected_component_id`. Existing parent `nc_…` identities are preserved. Incorrect legacy physical `ci_…` keys receive a new `nc_…` identity and move to `legacy_route_id` solely so old test-candidate URLs can resolve and redirect; existing child `ci_…` identities and integer foreign-key relationships are unchanged.

A definition may be archived only after its active node-assignment count reaches zero; normal library and Add Component queries exclude archived definitions, while historical removed connected components and capability instances retain their definition relationships. Archived seed identities are never recreated or reactivated by startup initialization. Definition capability edits reconcile active children transactionally: additions create new identities, removals preserve children as removed, and re-addition creates a new `ci_…` identity.

Legacy measurements currently identify sources only by `sensor_type` strings. No normalized measurement-to-capability-instance mapping exists, so the dashboard deliberately preserves its existing source labels rather than assigning an arbitrary connected-component label. A future explicit firmware/configuration mapping can safely enable that synchronization without rewriting telemetry.

Firmware publishes a complete `capabilities` array as a metadata-only message on startup and each MQTT reconnect. The subscriber validates every key before atomically replacing the reported set. An unknown key rejects the entire report and preserves the prior set. Legacy reading messages without capabilities remain unchanged.

Capability state is `unknown` before any report, `capability_mismatch` when a reported set omits an expected key, and otherwise `healthy`; extra reported functions are informational. Overall health applies disabled, offline, and unknown runtime precedence before this capability state.
