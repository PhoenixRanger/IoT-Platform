# v1.15.0 — Sensor & Actuator Component Model

v1.15.0 introduces a normalized physical component layer beneath the generic
capability registry. Reusable sensor and actuator definitions map to one or more
module-side interfaces and generic capabilities. Node inventory connects those
definitions with editable label, location, and zone metadata. Each connected
component materializes one child capability instance per provided capability;
the child capability instances own the immutable opaque `ci_…` identifiers.

Component definitions provide sensor/actuator capabilities only. Communication
capabilities such as Wi-Fi and LoRaWAN remain in the generic registry for
runtime reporting but are not assignable through the Component Library.

Active capability instances derive the node's count-aware Expected sensing and actuation
capabilities. Firmware-reported capabilities remain an independent, type-level
set; inventory does not imply runtime health and no reported multiplicity is
invented. Legacy expected-capability rows are preserved only for storage/API
compatibility and never contribute to current Expected state. A node without
active component inventory therefore has no Expected capabilities, and the
Technical UI no longer offers manual Expected editing.

Removal is lifecycle-based: the connected component and its active capability
instances become `removed`, retain their identities and metadata, and
immediately stop contributing to Expected capabilities.
Removal neither changes firmware nor blocks continued telemetry ingestion.

Component Library deletion is lifecycle-based as well. Definitions with active
node assignments cannot be removed. Once all assignments are removed, the
definition is archived and excluded from the library and Add Component flow,
while historical node-component records retain their definition relationship.

The final parent schema is `connected_components.connected_component_id`.
Existing parent `nc_…` values remain stable; incorrect physical `ci_…` values
from intermediate candidates are replaced with new `nc_…` IDs and retained
only as hidden legacy URL aliases. Existing true child `ci_…` identities remain
unchanged. Component definitions retain internal `definition_key` values for
seed and API routing compatibility, but the Component Library neither displays
nor asks users to manage them; custom definitions receive generated keys.
Legacy telemetry lacks an explicit capability-instance mapping, so the dashboard
retains its existing source labels rather than guessing associations.

The release adds the global Component Library, node Technical inventory
workflows, and a physical-component detail view. It does not add component
functions, board/pin mapping, desired-state configuration, remote commands,
instance-aware reporting, or firmware changes.
