# v1.14.0 — Groups, Tags & Fleet Organization

v1.14.0 adds reusable groups and tags through normalized definitions and
many-to-many node memberships. Fleet Organization provides definition creation,
rename, deletion, and grouped membership counts. Deleting a definition removes
only its memberships and never its nodes.

The Fleet Registry now displays a bounded group/tag summary with accessible
membership previews. Search combines with Group, Tag, expected Capability,
Runtime Status, and Overall Health filters. Values within a family use OR;
families use AND. Selection remains keyed by immutable `node_id`, survives
visibility changes and refreshes, and supports Select All for visible matches,
global Unselect All, and exactly four transactional Bulk Actions: add/remove
groups and apply/remove tags.

Node Details owns human-facing registry and organization editing. The separate
Technical view owns runtime, device, hardware, firmware, and existing capability
inspection/editing. The legacy category database/API contract remains compatible
but is not part of fleet organization or filtering.

This release adds no category subsystem, destructive lifecycle action, firmware,
MQTT, telemetry protocol, or OTA change. Existing v1.13 databases migrate
additively and require no firmware update.
