# v1.10.1 — Initial Public Release

v1.10.1 is a public-release hardening patch over v1.10.0. Its working tree is intended to be copied later into a separate public repository as a fresh initial commit. The historical private repository has not been scrubbed or rewritten.

## Changes

- generalized private LAN addresses, usernames, filesystem paths, node examples, and OTA hostnames in public documentation and configuration examples
- confirmed that tracked firmware secret templates contain placeholders only and that populated secret files remain local
- strengthened ignore coverage for local environments, caches, databases and journals, backups, firmware secrets, and PlatformIO output
- marked anonymous Mosquitto on all interfaces as a development/trusted-LAN example, not production guidance
- added public-facing project status, configuration guidance, and milestone history
- preserved v1.10.0 backend, database, MQTT, dashboard, firmware, OTA, and deployment behavior

## Compatibility note

Node ID and OTA hostname are configured in each firmware project's ignored local `include/secrets.h`; tracked example files use the generic identities `environment_node_001` and `irrigation_controller_001`. Existing deployments preserve their current MQTT topics, node records, and OTA targets by retaining their established identity values in that local configuration when adopting v1.10.1.

Firmware family versions remain independently set to v1.0.0 in their respective `VERSION` files.

## Security scope

This release does not add MQTT authentication, MQTT TLS, certificate infrastructure, OTA redesign, or history rewriting. Operators are responsible for using authenticated MQTT, suitable network restrictions and firewalling, unique strong OTA passwords, and other controls appropriate to production deployments.
