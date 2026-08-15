# v1.11.0 — Node Registry & Management Foundation

v1.11.0 introduces the first node management interface on the existing node-details page. Stable `node_id` values remain immutable technical identities, while operators can edit a node's name, location, category, optional GPS coordinates, and administrative enabled state.

Device-reported MQTT metadata is restricted to legacy node type, hardware model/revision, firmware name/version, and OTA hostname. Disabling a node changes its displayed status but deliberately does not stop HTTP or MQTT telemetry storage.

The additive SQLite migration preserves existing data and defaults existing nodes to enabled. A targeted measurements index supports complete recent reporting cycles without scanning and grouping full measurement history. Groups, tags, capabilities, remote configuration, alerts, automation, and fleet operations remain outside this release.
