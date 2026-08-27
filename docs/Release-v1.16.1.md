# v1.16.1 — Explicit Telemetry Reporting Cycles

v1.16.1 fixes dashboard row fragmentation when the independent MQTT packets
from one physical acquisition cycle cross server timestamp boundaries. The only
new runtime concept is the opaque `cycle_id`.

Both firmware targets generate one 64-bit random boot ID during startup and
keep a `uint32_t` sequence in RAM. Each reporting loop increments the sequence
once and reuses `cy_<16 lowercase hex boot ID>_<decimal sequence>` for every
valid channel packet in that cycle. Missing readings are omitted. Counters are
not persisted or provisioned, and firmware adds no clock or time semantics.

Canonical Instance telemetry now requires `node_id`, `instance_id`, `cycle_id`,
`value`, and `unit`. The subscriber validates the cycle format and stores it on
the Instance measurement and any RSSI/uptime diagnostic rows from that packet.
Capability-only metadata reports remain independent and require no cycle ID.

The additive, idempotent migration adds nullable
`measurements.measurement_cycle_id`; historical rows remain NULL without
backfill. A partial `(node_id, measurement_cycle_id, timestamp, id)` index
supports bounded retrieval of selected explicit cycles. Recent readings first
walk the existing node/timestamp index until the configured number of logical
groups is found. New measurements group by cycle ID, historical measurements
group by exact timestamp, and mixed results preserve the existing response
shape. An explicit cycle displays its earliest server-ingestion timestamp.

This release does not add `sampled_at`, `received_at`, time synchronization,
offline buffering, acknowledgements, batching requirements, historical
backfill, or any v1.17+ platform feature.
