# v1.16.0 — Capability Instance Runtime Identity & Telemetry Integration

v1.16.0 connects the normalized Capability Instances introduced in v1.15 to
new runtime telemetry. MQTT readings identify exactly one active channel with
`node_id`, `instance_id`, `value`, and `unit`. Ingestion validates the opaque
`ci_…` identifier and its owning node before inserting a measurement; it never
infers inventory from labels, capabilities, component types, or legacy names.

Capability Instances now have editable labels. Existing Instances receive the
associated Generic Capability display name during the bounded startup
migration, and newly reconciled Instances receive the same default. Renaming a
label changes only presentation: Component and Capability relationships,
Instance identity, Expected counts, and telemetry rows remain unchanged.

Measurements gain a nullable `capability_instance_id`, preserving every legacy
row without backfill or remapping. New telemetry stores the explicit reference.
The dashboard returns legacy historical channels as before and new channels by
immutable Instance ID, then resolves labels in one node-scoped metadata request.
The existing bounded recent-cycle query remains in place, with a partial
Instance/timestamp index added for recurring series access.

Both firmware targets emit one packet per physical sensor channel. Deployment
Instance IDs are configured in the local ignored `secrets.h`; tracked example
configuration intentionally contains placeholders because authoritative live
IDs are not present in this checkout. Firmware does not generate IDs.

This release does not add enablement, semantic functions, hardware mapping,
Node Configuration, remote configuration, automation, historical remapping, or
a legacy telemetry binding path.
