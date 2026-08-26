# IoT Dashboard

A Raspberry Pi + ESP32 environmental monitoring dashboard and early-stage agricultural IoT platform.

## Current Version

**v1.16.0 — Capability Instance Runtime Identity & Telemetry Integration**

This release makes stable `ci_…` Capability Instance IDs the canonical identity of new runtime telemetry. Instance labels are editable presentation metadata used by the dashboard without changing the underlying telemetry series.

## Features

- Original ESP32/DHT22 and Heltec WiFi LoRa 32 V3 dual-climate nodes
- Capability Instance-aware MQTT ingestion with strict node ownership and lifecycle validation
- Normalized SQLite measurements plus persistent node hardware/firmware metadata
- Dynamic node/sensor selectors, cards, historical charts, node status, RSSI, and uptime
- Editable node names, locations, categories, GPS coordinates, and administrative enabled state
- Generic sensor, actuator, and communication capabilities with expected/reported comparison
- Reusable sensor/actuator definitions with normalized interface and non-communication capability mappings
- Connected-component inventory with editable child labels and stable `ci_…` runtime identities
- Count-aware Expected capabilities derived from active capability instances
- Clickable dashboard status tile and `/nodes/<node_id>` node management details
- Compact `/nodes` fleet registry with search, selection, and node navigation
- Fleet Organization, group/tag membership management, multi-family filtering, and bulk organization actions
- PlatformIO USB and authenticated local Wi-Fi OTA firmware uploads
- Flask APIs and Raspberry Pi systemd deployment

## Architecture

```text
PlatformIO ESP32 nodes → MQTT → subscriber → SQLite → Flask API → dashboard
                           HTTP debug fallback ────────┘
```

Both firmware families remain in this monorepo. Shared Wi-Fi, MQTT metadata, OTA, and identity helpers live under `firmware/shared/`; application and sensor logic stays family-specific.

```text
firmware/
├── shared/{wifi,mqtt,ota,diagnostics}
├── environment-node/{src,include,platformio.ini,VERSION}
└── irrigation-controller/{src,include,platformio.ini,VERSION}
```

Firmware has independent semantic versions, unrelated to the platform release. Formal history begins at `environment-node` **v1.0.0** and `irrigation-controller` **v1.0.0**; each `VERSION` file is its build-time source of truth.

## Data and MQTT

Nodes publish one Capability Instance-aware reading per packet to `sensors/<node_id>/readings`. The server rejects unknown, inactive, malformed, or cross-node Instance IDs and never creates inventory from telemetry. Firmware continues to report its complete type-level capability set on MQTT connection/reconnection. Historical legacy measurement rows remain readable, but legacy sensor-name packets are no longer a runtime ingestion protocol.

```json
{"node_id":"irrigation_controller_001","instance_id":"ci_4004cf91b3","value":24.8,"unit":"C"}
```

On startup, `init_db()` safely adds nullable Instance identity to measurements and labels to the small Capability Instance inventory. Existing measurements and identities are retained; no history backfill occurs. A partial `(capability_instance_id, timestamp DESC, id DESC)` index supports Instance-series queries while the existing node/timestamp index continues to bound dashboard refreshes.

HTTP fallback remains:

```json
{"node_id":"environment_node_001","readings":{"temperature":24.8,"humidity":51.2}}
```

## Firmware setup and OTA

Install [PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/index.html). For either firmware directory:

```bash
cp include/secrets.example.h include/secrets.h
```

Set Wi-Fi, MQTT server, node ID, OTA hostname, and a strong OTA password. The secret file and `.pio` output are ignored. USB is required for the first OTA-capable image and is always the recovery method:

```bash
cd firmware/irrigation-controller
pio run -e usb
pio run -e usb -t upload --upload-port /dev/ttyUSB0
```

After the node reconnects, export the same password and upload by unique hostname or stable local IP:

```bash
export OTA_PASSWORD='the-same-password'
pio run -e ota -t upload --upload-port irrigation-controller-001.local
```

The OTA partition scheme is retained in every environment. Do not hardcode transient node IPs. See [Deployment](docs/Deployment.md), [Operations](docs/Operations.md), and [Remote Access](docs/RemoteAccess.md) for the Raspberry Pi and remote SSH workflow.

## API

- `GET /` — dashboard
- `POST /api/data` — HTTP fallback ingestion
- `GET /api/nodes` — registered nodes
- `GET /api/nodes/overview` — compact fleet runtime and health overview
- `GET|POST /api/groups` and `/api/tags` — reusable fleet definitions
- `PATCH|DELETE /api/groups/<id>` and `/api/tags/<id>` — rename/delete definitions
- `GET|POST /api/nodes/<node_id>/organization` — individual memberships
- `POST /api/fleet/organization` — transactional bulk membership mutation
- `GET /api/capabilities` — system capability registry
- `GET|POST /api/components` — list/create reusable component definitions
- `GET|PATCH|DELETE /api/components/<definition_key>` — inspect/update or lifecycle-remove an unassigned definition; the key is an internal routing identity and is not shown in the library UI
- `GET|POST /api/nodes/<node_id>/components` — active inventory (add `?include_removed=true` for history) and connected-component creation
- `GET|PATCH|DELETE /api/nodes/<node_id>/components/<connected_component_id>` — inspect/edit metadata or lifecycle-remove a connected component
- `PUT /api/nodes/<node_id>/capabilities` — legacy expected-capability storage compatibility endpoint; it does not affect current component-derived Expected state
- `GET /api/nodes/<node_id>` — metadata and calculated runtime state
- `PATCH /api/nodes/<node_id>` — update name, location, category, GPS, or enabled state
- `GET /api/readings?node_id=<node_id>` — readings
- `GET /api/nodes/<node_id>/capability-instances` — active Instance metadata for dashboard presentation
- `PATCH /api/nodes/<node_id>/capability-instances/<ci_…>` — update an Instance label
- `GET /api/node-status?node_id=<node_id>` — compatible status endpoint
- `GET /nodes/<node_id>` — node-details page
- `GET /nodes/<node_id>/technical` — technical/runtime/capability view
- `GET /nodes` — fleet registry and node navigation
- `GET /fleet/organization` — group/tag definition management
- `GET /components` — reusable Component Library
- `GET /nodes/<node_id>/components/<legacy_route_id>` — connected-component detail

Status is disabled when administratively disabled; otherwise it is online when the latest measurement is at most 60 seconds old, offline when older, and unknown with no measurements. Missing metadata is returned as `null`.

## Configuration and secrets

Backend settings can be supplied with `MQTT_HOST`, `MQTT_PORT`, `MQTT_TOPIC`, and `DEFAULT_NODE_ID`; the default node ID is `environment_node_001`. Existing deployments can retain their established default by setting `DEFAULT_NODE_ID` in their local service environment. Firmware configuration follows an example-and-local-copy model: each tracked `include/secrets.example.h` contains placeholders and a generic private-network broker address, while the populated `include/secrets.h` stays local and ignored. `.env`, databases, backups, Python environments, and PlatformIO build output are also ignored.

The simple anonymous Mosquitto configuration in the deployment guide is for development or a trusted, firewalled LAN only. Production deployments should use authenticated MQTT, network restrictions/firewalling, and security controls appropriate to the deployment.

## Run locally

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
python run.py
# separate shell/service
python -m app.mqtt_subscriber
```

## Development history

The public repository is intended to begin with the mature v1.10.1 working tree rather than the earlier private Git history. These milestones preserve the project's evolution for context without republishing historical source:

- **v1.0** — initial ESP32 sensor-to-Flask dashboard prototype.
- **v1.1** — modular Flask backend and deployment reliability fixes.
- **v1.2** — normalized multi-node, multi-sensor SQLite data model.
- **v1.3** — multi-node HTTP ingestion and ESP32 environment-node firmware.
- **v1.4** — dynamic multi-node dashboard and architecture documentation.
- **v1.5.0** — Mosquitto MQTT ingestion and ESP32 MQTT publishing.
- **v1.5.1–v1.5.2** — deployment cleanup and MQTT reliability hardening.
- **v1.6** — private remote access and operational documentation through Tailscale.
- **v1.7** — lightweight node status monitoring.
- **v1.8.0–v1.8.1** — RSSI/uptime telemetry and dashboard layout polish.
- **v1.9** — Heltec dual-climate irrigation-controller support and sensor recovery.
- **v1.10.0** — independently versioned PlatformIO firmware, authenticated OTA, node metadata, and node details.
- **v1.10.1** — sanitized initial-public-release baseline with no intended functional changes.
- **v1.11.0** — node registry management, metadata ownership boundaries, and complete indexed recent reporting cycles.
- **v1.12.0** — generic capability registry, expected/reported capability state, health, UI, and firmware reporting.
- **v1.13.0** — fleet registry, search and selection foundation, and direct node navigation.
- **v1.14.0** — groups, tags, fleet filters, bulk organization, and Details/Technical separation.
- **v1.15.0** — reusable component definitions, node physical inventory, lifecycle removal, and component-derived Expected capabilities.
- **v1.16.0** — immutable Capability Instance runtime telemetry identity, editable labels, and dashboard integration.

Future work continues toward MQTT security, LoRaWAN, actuator and node management, and a dedicated Linux property server. See the architecture and operations documents for the current design and workflows.
