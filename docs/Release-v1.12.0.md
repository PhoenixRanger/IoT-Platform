# v1.12.0 — Generic Capability Model

v1.12.0 adds a normalized, hardware-independent capability layer. The system registry seeds stable sensor, actuator, and communication keys. Operators replace a node's expected set through a dedicated API and node-details editor; firmware owns a separate complete reported set.

Capability comparison reports expected, reported, missing, and additional functions. No report is unknown, a missing expected function is a capability mismatch, and additional reported functions remain informational. Runtime disabled/offline/unknown states take precedence in overall health.

Both firmware families publish declarative capability metadata at startup and after MQTT reconnect through the shared metadata helper. Unknown device keys reject the complete report without changing the previous set or registry. Existing firmware and payloads without capability metadata continue to work.

This release does not add physical components, boards, pins, templates, groups, configuration synchronization, actuator commands, alerts, or automation.
