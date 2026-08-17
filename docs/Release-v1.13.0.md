# v1.13.0 — Fleet Registry & Node Navigation

v1.13.0 adds the first dedicated fleet registry at `/nodes`. It presents each
registered node's display name, immutable ID, runtime indicator, backend-derived
health, and explicit dashboard and details links. Operators can search names and
IDs locally and enter a temporary selection mode whose Select All action applies
to the currently visible search results.

The compact `/api/nodes/overview` endpoint keeps the existing `/api/nodes`
contract lightweight. It calculates status and health with the same backend rules
as node details and seeks the newest measurement per registered node through the
existing `(node_id, timestamp DESC, id DESC)` index. No fleet metadata or
selection is persisted, and this release introduces no database schema or
firmware changes.
