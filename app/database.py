import sqlite3
import re
import secrets
from datetime import datetime

from app.config import DB_NAME, DEFAULT_NODE_ID, READING_LIMIT


SENSOR_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "outside_temperature": "°C",
    "outside_humidity": "%",
    "outside_pressure": "hPa",
    "enclosure_temperature": "°C",
    "enclosure_humidity": "%",
    "enclosure_pressure": "hPa",
    "soil_moisture": "%",
    "soil_temperature": "°C",
    "rssi": "dBm",
    "uptime_seconds": "s",
    "battery_voltage": "V",
    "battery_percentage": "%",
    "air_pressure": "hPa",
    "light_intensity": "lux",
    "rainfall": "mm",
    "wind_speed": "m/s",
    "wind_direction": "°",
    "solar_radiation": "W/m²",
    "water_level": "%",
    "water_flow": "L/min",
    "ph": "pH",
    "ec": "mS/cm",
}

CAPABILITY_DEFINITIONS = (
    ("temperature_measurement", "Temperature", "sensor", "Measures temperature."),
    ("humidity_measurement", "Humidity", "sensor", "Measures relative humidity."),
    ("pressure_measurement", "Pressure", "sensor", "Measures atmospheric pressure."),
    ("soil_moisture_measurement", "Soil Moisture", "sensor", "Measures soil moisture."),
    ("soil_temperature_measurement", "Soil Temperature", "sensor", "Measures soil temperature."),
    ("relay_control", "Relay Control", "actuator", "Controls a relay output."),
    ("pump_control", "Pump Control", "actuator", "Controls a pump."),
    ("valve_control", "Valve Control", "actuator", "Controls a valve."),
    ("switched_output", "Switched Output", "actuator", "Provides a generic switched output."),
    ("wifi", "Wi-Fi", "communication", "Communicates over Wi-Fi."),
    ("lorawan", "LoRaWAN", "communication", "Communicates over LoRaWAN."),
)

COMPONENT_CLASSES = {"sensor", "actuator"}
COMPONENT_INTERFACE_TYPES = {"i2c", "spi", "uart", "analog_signal", "digital_signal"}
DEFINITION_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
COMPONENT_SEEDS = (
    {
        "definition_key": "te-ms8607", "display_name": "TE Connectivity MS8607",
        "manufacturer": "TE Connectivity", "model": "MS8607", "component_class": "sensor",
        "interfaces": ["i2c"],
        "capabilities": ["temperature_measurement", "humidity_measurement", "pressure_measurement"],
    },
    {
        "definition_key": "aosong-dht22", "display_name": "Aosong DHT22 / AM2302",
        "manufacturer": "Aosong", "model": "DHT22 / AM2302", "component_class": "sensor",
        "interfaces": ["digital_signal"],
        "capabilities": ["temperature_measurement", "humidity_measurement"],
    },
    {
        "definition_key": "generic-analog-soil-moisture-sensor",
        "display_name": "Generic Analog Soil-Moisture Sensor", "manufacturer": None,
        "model": None, "component_class": "sensor", "interfaces": ["analog_signal"],
        "capabilities": ["soil_moisture_measurement"],
    },
    {
        "definition_key": "generic-mosfet-switch-module",
        "display_name": "Generic MOSFET Switch Module", "manufacturer": None,
        "model": None, "component_class": "actuator", "interfaces": ["digital_signal"],
        "capabilities": ["switched_output"],
    },
)


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            location TEXT,
            node_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Add registry and device-reported metadata in place so existing sensor.db
    # files, node identities, and telemetry relationships are preserved.
    existing_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(nodes)").fetchall()
    }
    additive_columns = {
        "hardware_model": "TEXT",
        "firmware_name": "TEXT",
        "firmware_version": "TEXT",
        "ota_hostname": "TEXT",
        "category": "TEXT",
        "latitude": "REAL",
        "longitude": "REAL",
        "enabled": "INTEGER NOT NULL DEFAULT 1",
    }
    for column, definition in additive_columns.items():
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE nodes ADD COLUMN {column} {definition}")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_db_id INTEGER NOT NULL,
            sensor_type TEXT NOT NULL,
            unit TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(node_db_id, sensor_type),
            FOREIGN KEY (node_db_id) REFERENCES nodes(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_db_id INTEGER NOT NULL,
            node_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            value REAL NOT NULL,
            unit TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id)
        )
    """)

    # Supports bounded recent-cycle lookups for one node. The dashboard first
    # walks this covering index only until it finds READING_LIMIT timestamps,
    # then uses the same index to retrieve every row in those cycles.
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_measurements_node_timestamp_id
        ON measurements (node_id, timestamp DESC, id DESC)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_db_id INTEGER NOT NULL,
            command_type TEXT NOT NULL,
            payload TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_db_id INTEGER,
            event_type TEXT NOT NULL,
            message TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS capabilities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capability_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            capability_class TEXT NOT NULL
                CHECK (capability_class IN ('sensor', 'actuator', 'communication')),
            description TEXT NOT NULL
        )
    """)
    cur.executemany("""
        INSERT INTO capabilities
            (capability_key, display_name, capability_class, description)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(capability_key) DO UPDATE SET
            display_name = excluded.display_name,
            capability_class = excluded.capability_class,
            description = excluded.description
    """, CAPABILITY_DEFINITIONS)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_expected_capabilities (
            node_db_id INTEGER NOT NULL,
            capability_id INTEGER NOT NULL,
            PRIMARY KEY (node_db_id, capability_id),
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (capability_id) REFERENCES capabilities(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_capability_reports (
            node_db_id INTEGER PRIMARY KEY,
            reported_at TEXT NOT NULL,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_reported_capabilities (
            node_db_id INTEGER NOT NULL,
            capability_id INTEGER NOT NULL,
            reported_at TEXT NOT NULL,
            PRIMARY KEY (node_db_id, capability_id),
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (capability_id) REFERENCES capabilities(id)
        )
    """)
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_expected_capability
                   ON node_expected_capabilities (capability_id)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_reported_capability
                   ON node_reported_capabilities (capability_id)""")

    # Human-owned fleet organization is deliberately independent from node
    # identity, capabilities, and the legacy category field.
    for table in ("groups", "tags"):
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {table} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE
                    CHECK (length(trim(name)) > 0)
            )
        """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_groups (
            node_db_id INTEGER NOT NULL,
            group_id INTEGER NOT NULL,
            PRIMARY KEY (node_db_id, group_id),
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS node_tags (
            node_db_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (node_db_id, tag_id),
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_node_groups_group ON node_groups (group_id, node_db_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_node_tags_tag ON node_tags (tag_id, node_db_id)")

    # Reusable physical sensing/control hardware is normalized independently
    # from generic capabilities and from node-specific physical inventory.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS component_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            definition_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            manufacturer TEXT,
            model TEXT,
            component_class TEXT NOT NULL CHECK (component_class IN ('sensor', 'actuator')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            lifecycle_status TEXT NOT NULL DEFAULT 'active'
                CHECK (lifecycle_status IN ('active', 'removed')),
            removed_at TEXT
        )
    """)
    definition_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(component_definitions)").fetchall()
    }
    # v1.15 definition slugs are retained only as internal routing/seed keys.
    if "component_id" in definition_columns and "definition_key" not in definition_columns:
        cur.execute("ALTER TABLE component_definitions RENAME COLUMN component_id TO definition_key")
        definition_columns.remove("component_id")
        definition_columns.add("definition_key")
    if "lifecycle_status" not in definition_columns:
        cur.execute("""ALTER TABLE component_definitions
                       ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'active'""")
    if "removed_at" not in definition_columns:
        cur.execute("ALTER TABLE component_definitions ADD COLUMN removed_at TEXT")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS component_interface_requirements (
            component_definition_id INTEGER NOT NULL,
            interface_type TEXT NOT NULL CHECK (interface_type IN
                ('i2c', 'spi', 'uart', 'analog_signal', 'digital_signal')),
            PRIMARY KEY (component_definition_id, interface_type),
            FOREIGN KEY (component_definition_id) REFERENCES component_definitions(id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS component_capabilities (
            component_definition_id INTEGER NOT NULL,
            capability_id INTEGER NOT NULL,
            PRIMARY KEY (component_definition_id, capability_id),
            FOREIGN KEY (component_definition_id) REFERENCES component_definitions(id) ON DELETE CASCADE,
            FOREIGN KEY (capability_id) REFERENCES capabilities(id)
        )
    """)
    # PR #33 called connected physical modules "instances". Rename that small
    # management table and preserve old URL keys only as aliases.
    tables = {row[0] for row in cur.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()}
    if "node_component_instances" in tables and "connected_components" not in tables:
        cur.execute("ALTER TABLE node_component_instances RENAME TO connected_components")
    connected_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(connected_components)").fetchall()
    } if "connected_components" in {row[0] for row in cur.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()} else set()
    if "instance_id" in connected_columns and "connected_component_id" not in connected_columns:
        cur.execute("ALTER TABLE connected_components RENAME COLUMN instance_id TO connected_component_id")
        connected_columns.remove("instance_id")
        connected_columns.add("connected_component_id")
    if connected_columns and "legacy_route_id" not in connected_columns:
        cur.execute("ALTER TABLE connected_components ADD COLUMN legacy_route_id TEXT")
    if connected_columns:
        legacy_rows = cur.execute("""SELECT id, connected_component_id
            FROM connected_components WHERE substr(connected_component_id, 1, 3) = 'ci_'""").fetchall()
        for connected_db_id, legacy_route_id in legacy_rows:
            for _ in range(12):
                replacement = f"nc_{secrets.token_hex(5)}"
                if cur.execute("""SELECT 1 FROM connected_components
                    WHERE connected_component_id = ?""", (replacement,)).fetchone() is None:
                    break
            else:
                raise RuntimeError("Unable to migrate a unique Connected Component ID")
            cur.execute("""UPDATE connected_components
                SET connected_component_id = ?, legacy_route_id = ? WHERE id = ?""",
                (replacement, legacy_route_id, connected_db_id))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS connected_components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            connected_component_id TEXT NOT NULL UNIQUE,
            legacy_route_id TEXT UNIQUE,
            node_db_id INTEGER NOT NULL,
            component_definition_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            location TEXT,
            zone TEXT,
            lifecycle_status TEXT NOT NULL DEFAULT 'active'
                CHECK (lifecycle_status IN ('active', 'removed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            removed_at TEXT,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE RESTRICT,
            FOREIGN KEY (component_definition_id) REFERENCES component_definitions(id) ON DELETE RESTRICT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS component_capability_instances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            capability_instance_id TEXT NOT NULL UNIQUE,
            connected_component_id INTEGER NOT NULL,
            capability_id INTEGER NOT NULL,
            lifecycle_status TEXT NOT NULL DEFAULT 'active'
                CHECK (lifecycle_status IN ('active', 'removed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            removed_at TEXT,
            FOREIGN KEY (connected_component_id)
                REFERENCES connected_components(id) ON DELETE RESTRICT,
            FOREIGN KEY (capability_id) REFERENCES capabilities(id) ON DELETE RESTRICT
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_component_interfaces_definition ON component_interface_requirements (component_definition_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_component_capabilities_definition ON component_capabilities (component_definition_id, capability_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_connected_components_node_active ON connected_components (node_db_id, lifecycle_status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_connected_components_definition ON connected_components (component_definition_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_component_definitions_lifecycle ON component_definitions (lifecycle_status, display_name)")
    cur.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_active_capability_instance
                   ON component_capability_instances
                       (connected_component_id, capability_id)
                   WHERE lifecycle_status = 'active'""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_capability_instances_component
                   ON component_capability_instances
                       (connected_component_id, lifecycle_status)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS idx_capability_instances_capability
                   ON component_capability_instances
                       (capability_id, lifecycle_status)""")
    _seed_component_definitions(cur)
    _reconcile_capability_instances(cur, include_removed_missing=True)

    conn.commit()
    conn.close()


def _seed_component_definitions(cur):
    """Idempotently add verified/truthfully generic project hardware definitions."""
    timestamp = now_string()
    capability_ids = dict(cur.execute(
        "SELECT capability_key, id FROM capabilities"
    ).fetchall())
    for seed in COMPONENT_SEEDS:
        inserted = cur.execute("""
            INSERT INTO component_definitions
                (definition_key, display_name, manufacturer, model, component_class, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(definition_key) DO NOTHING
        """, (seed["definition_key"], seed["display_name"], seed["manufacturer"], seed["model"],
              seed["component_class"], timestamp, timestamp)).rowcount
        definition_id = cur.execute(
            "SELECT id FROM component_definitions WHERE definition_key = ?", (seed["definition_key"],)
        ).fetchone()[0]
        if not inserted:
            continue
        cur.executemany("""
            INSERT OR IGNORE INTO component_interface_requirements
                (component_definition_id, interface_type) VALUES (?, ?)
        """, [(definition_id, item) for item in seed["interfaces"]])
        cur.executemany("""
            INSERT OR IGNORE INTO component_capabilities
                (component_definition_id, capability_id) VALUES (?, ?)
        """, [(definition_id, capability_ids[item]) for item in seed["capabilities"]])


def get_or_create_node(cur, node_id, name=None, location=None, node_type="esp32_wifi"):
    cur.execute("SELECT id FROM nodes WHERE node_id = ?", (node_id,))
    row = cur.fetchone()

    if row:
        return row[0]

    cur.execute(
        """
        INSERT INTO nodes (node_id, name, location, node_type, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (node_id, name or node_id, location, node_type, now_string())
    )

    return cur.lastrowid


def get_nodes():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT node_id, name, location, category, latitude, longitude,
               enabled, node_type, created_at
        FROM nodes
        ORDER BY node_id ASC
    """)

    rows = cur.fetchall()
    conn.close()

    return [
        {
            "node_id": row[0],
            "name": row[1],
            "location": row[2],
            "category": row[3],
            "latitude": row[4],
            "longitude": row[5],
            "enabled": bool(row[6]),
            "node_type": row[7],
            "created_at": row[8]
        }
        for row in rows
    ]


DEVICE_METADATA_FIELDS = (
    "node_type",
    "hardware_model",
    "firmware_name",
    "firmware_version",
    "ota_hostname",
)


def update_device_metadata(node_id, metadata):
    """Update only device-owned metadata, creating its node when necessary."""
    values = {key: metadata[key] for key in DEVICE_METADATA_FIELDS if key in metadata}
    conn = get_connection()
    cur = conn.cursor()
    get_or_create_node(cur, node_id)
    if values:
        assignments = ", ".join(f"{key} = ?" for key in values)
        cur.execute(
            f"UPDATE nodes SET {assignments} WHERE node_id = ?",
            (*values.values(), node_id),
        )
    conn.commit()
    conn.close()


# Backward-compatible Python entry point with restricted v1.11 ownership.
update_node_metadata = update_device_metadata


def update_node_registry(node_id, values):
    """Update validated user-owned registry fields on an existing node."""
    conn = get_connection()
    cur = conn.cursor()
    assignments = ", ".join(f"{key} = ?" for key in values)
    parameters = [int(value) if key == "enabled" else value for key, value in values.items()]
    cur.execute(
        f"UPDATE nodes SET {assignments} WHERE node_id = ?",
        (*parameters, node_id),
    )
    updated = cur.rowcount > 0
    conn.commit()
    conn.close()
    return updated


def get_node(node_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT node_id, name, location, category, latitude, longitude,
               enabled, node_type, hardware_model,
               firmware_name, firmware_version, ota_hostname, created_at
        FROM nodes WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    node = dict(row)
    node["enabled"] = bool(node["enabled"])
    return node


def _clean_optional_text(value, field):
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field} must be a string or null")
    return value.strip() or None if isinstance(value, str) else None


def _validate_component_definition(values, creating=False):
    required = {"display_name", "component_class",
                "interfaces", "capabilities"} if creating else set()
    allowed = {"display_name", "manufacturer", "model", "component_class", "interfaces", "capabilities"}
    # Accept an explicitly named legacy/API definition key for compatibility;
    # the normal UI never asks users to create or edit one.
    if creating:
        allowed.add("definition_key")
    if not isinstance(values, dict) or required - set(values) or set(values) - allowed:
        if creating:
            raise ValueError("A complete component definition is required")
        raise ValueError("Request contains unsupported or missing fields")
    result = {}
    if creating:
        result.update({"manufacturer": None, "model": None})
    if "definition_key" in values:
        definition_key = values["definition_key"]
        if not isinstance(definition_key, str) or not DEFINITION_KEY_PATTERN.fullmatch(definition_key):
            raise ValueError(
                "definition_key must contain lowercase letters, numbers, and single hyphens"
            )
        result["definition_key"] = definition_key
    if "display_name" in values:
        if not isinstance(values["display_name"], str) or not values["display_name"].strip():
            raise ValueError("display_name must be a non-empty string")
        result["display_name"] = values["display_name"].strip()
    for field in ("manufacturer", "model"):
        if field in values:
            result[field] = _clean_optional_text(values[field], field)
    if "component_class" in values:
        if values["component_class"] not in COMPONENT_CLASSES:
            raise ValueError("component_class must be sensor or actuator")
        result["component_class"] = values["component_class"]
    for field, allowed_values in (("interfaces", COMPONENT_INTERFACE_TYPES),):
        if field in values:
            items = values[field]
            if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
                raise ValueError(f"{field} must be a list of strings")
            if not items:
                raise ValueError("A component definition must have at least one interface requirement")
            if len(items) != len(set(items)):
                raise ValueError(f"Duplicate {field} are not allowed")
            unknown = sorted(set(items) - allowed_values)
            if unknown:
                raise ValueError(f"Unknown interface type(s): {', '.join(unknown)}")
            result[field] = items
    if "capabilities" in values:
        items = values["capabilities"]
        if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
            raise ValueError("capabilities must be a list of capability keys")
        if not items:
            raise ValueError("A component definition must provide at least one capability")
        if len(items) != len(set(items)):
            raise ValueError("Duplicate capabilities are not allowed")
        result["capabilities"] = items
    return result


def _component_rows(conn, definition_key=None, include_removed=False):
    """Load the small component library and both relationships without N+1 queries."""
    conn.row_factory = sqlite3.Row
    clauses, params = [], []
    if definition_key is not None:
        clauses.append("definition.definition_key = ?")
        params.append(definition_key)
    if not include_removed:
        clauses.append("definition.lifecycle_status = 'active'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"""
        SELECT definition.*,
               SUM(CASE WHEN connected.lifecycle_status = 'active' THEN 1 ELSE 0 END)
                   AS active_connected_component_count,
               COUNT(connected.id) AS historical_connected_component_count
        FROM component_definitions AS definition
        LEFT JOIN connected_components AS connected
          ON connected.component_definition_id = definition.id
        {where}
        GROUP BY definition.id
        ORDER BY definition.display_name COLLATE NOCASE, definition.definition_key
    """, params).fetchall()
    definitions = {row["id"]: {key: row[key] for key in (
        "definition_key", "display_name", "manufacturer", "model", "component_class",
        "created_at", "updated_at", "lifecycle_status", "removed_at",
        "active_connected_component_count", "historical_connected_component_count")}
        | {"interfaces": [], "capabilities": []} for row in rows}
    if not definitions:
        return []
    ids = list(definitions)
    placeholders = ", ".join("?" for _ in ids)
    for row in conn.execute(f"""
        SELECT component_definition_id, interface_type
        FROM component_interface_requirements
        WHERE component_definition_id IN ({placeholders})
        ORDER BY interface_type
    """, ids):
        definitions[row["component_definition_id"]]["interfaces"].append(row["interface_type"])
    for row in conn.execute(f"""
        SELECT mapping.component_definition_id, capability.capability_key,
               capability.display_name, capability.capability_class, capability.description
        FROM component_capabilities AS mapping
        JOIN capabilities AS capability ON capability.id = mapping.capability_id
        WHERE mapping.component_definition_id IN ({placeholders})
        ORDER BY capability.display_name
    """, ids):
        definitions[row["component_definition_id"]]["capabilities"].append({
            key: row[key] for key in ("capability_key", "display_name", "capability_class", "description")
        })
    return list(definitions.values())


def list_component_definitions(include_removed=False):
    conn = get_connection()
    rows = _component_rows(conn, include_removed=include_removed)
    conn.close()
    return rows


def get_component_definition(definition_key, include_removed=False):
    conn = get_connection()
    rows = _component_rows(conn, definition_key, include_removed)
    conn.close()
    return rows[0] if rows else None


def _replace_component_relationships(cur, definition_id, values):
    if "capabilities" in values:
        keys, capability_ids = _validated_component_capability_ids(cur, values["capabilities"])
        cur.execute("DELETE FROM component_capabilities WHERE component_definition_id = ?", (definition_id,))
        cur.executemany("INSERT INTO component_capabilities (component_definition_id, capability_id) VALUES (?, ?)",
                        [(definition_id, capability_ids[key]) for key in keys])
    if "interfaces" in values:
        cur.execute("DELETE FROM component_interface_requirements WHERE component_definition_id = ?", (definition_id,))
        cur.executemany("INSERT INTO component_interface_requirements (component_definition_id, interface_type) VALUES (?, ?)",
                        [(definition_id, item) for item in values["interfaces"]])


def create_component_definition(values):
    values = _validate_component_definition(values, creating=True)
    conn = get_connection()
    try:
        cur = conn.cursor()
        # Validate relationships before creating anything; capabilities are never implicit.
        _validated_component_capability_ids(cur, values["capabilities"])
        definition_key = values.get("definition_key")
        if definition_key is None:
            for _ in range(12):
                definition_key = f"def_{secrets.token_hex(5)}"
                if cur.execute("SELECT 1 FROM component_definitions WHERE definition_key = ?",
                               (definition_key,)).fetchone() is None:
                    break
            else:
                raise RuntimeError("Unable to generate a unique definition key")
        elif cur.execute("SELECT 1 FROM component_definitions WHERE definition_key = ?",
                         (definition_key,)).fetchone() is not None:
            raise ValueError("A component definition with that definition_key already exists")
        timestamp = now_string()
        cur.execute("""INSERT INTO component_definitions
            (definition_key, display_name, manufacturer, model, component_class, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""", (definition_key,) + tuple(values[key] for key in (
                "display_name", "manufacturer", "model", "component_class")) + (timestamp, timestamp))
        _replace_component_relationships(cur, cur.lastrowid, values)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_component_definition(definition_key)


def update_component_definition(definition_key, values):
    if isinstance(values, dict) and "definition_key" in values:
        raise ValueError("definition_key is immutable")
    values = _validate_component_definition(values)
    if not values:
        raise ValueError("Request body must not be empty")
    conn = get_connection()
    try:
        cur = conn.cursor()
        row = cur.execute("""SELECT id FROM component_definitions
                             WHERE definition_key = ? AND lifecycle_status = 'active'""",
                          (definition_key,)).fetchone()
        if row is None:
            return None
        if "capabilities" in values:
            _validated_component_capability_ids(cur, values["capabilities"])
        metadata = {key: value for key, value in values.items() if key not in {"interfaces", "capabilities"}}
        if metadata:
            metadata["updated_at"] = now_string()
            assignments = ", ".join(f"{key} = ?" for key in metadata)
            cur.execute(f"UPDATE component_definitions SET {assignments} WHERE id = ?", (*metadata.values(), row[0]))
        _replace_component_relationships(cur, row[0], values)
        if "capabilities" in values:
            _reconcile_capability_instances(
                cur, component_definition_id=row[0], include_removed_missing=False
            )
        if set(values) <= {"interfaces", "capabilities"}:
            cur.execute("UPDATE component_definitions SET updated_at = ? WHERE id = ?", (now_string(), row[0]))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_component_definition(definition_key)


def delete_component_definition(definition_key):
    conn = get_connection()
    try:
        row = conn.execute("""SELECT id FROM component_definitions
                              WHERE definition_key = ? AND lifecycle_status = 'active'""",
                           (definition_key,)).fetchone()
        if row is None:
            return "missing"
        if conn.execute("""SELECT 1 FROM connected_components
                            WHERE component_definition_id = ?
                              AND lifecycle_status = 'active' LIMIT 1""", row).fetchone():
            return "active_reference"
        timestamp = now_string()
        conn.execute("""UPDATE component_definitions
                        SET lifecycle_status = 'removed', removed_at = ?, updated_at = ?
                        WHERE id = ?""", (timestamp, timestamp, row[0]))
        conn.commit()
        return "removed"
    finally:
        conn.close()


def _new_connected_component_id(cur):
    """Generate the immutable public identity for one connected physical module."""
    for _ in range(12):
        connected_component_id = f"nc_{secrets.token_hex(5)}"
        if cur.execute("SELECT 1 FROM connected_components WHERE connected_component_id = ?",
                       (connected_component_id,)).fetchone() is None:
            return connected_component_id
    raise RuntimeError("Unable to generate a unique Connected Component ID")


def _new_capability_instance_id(cur):
    for _ in range(12):
        capability_instance_id = f"ci_{secrets.token_hex(5)}"
        if cur.execute(
            """SELECT 1 FROM component_capability_instances
               WHERE capability_instance_id = ?""", (capability_instance_id,)
        ).fetchone() is None:
            return capability_instance_id
    raise RuntimeError("Unable to generate a unique capability-instance ID")


def _reconcile_capability_instances(
        cur, connected_component_ids=None, component_definition_id=None,
        include_removed_missing=False):
    """Reconcile normalized capability children without reusing removed identities."""
    clauses, parameters = [], []
    if connected_component_ids is not None:
        ids = list(dict.fromkeys(connected_component_ids))
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        clauses.append(f"connected.id IN ({placeholders})")
        parameters.extend(ids)
    if component_definition_id is not None:
        clauses.append("connected.component_definition_id = ?")
        parameters.append(component_definition_id)
    if not include_removed_missing:
        clauses.append("connected.lifecycle_status = 'active'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    connected = cur.execute(f"""
        SELECT connected.id, connected.component_definition_id,
               connected.lifecycle_status, connected.removed_at
        FROM connected_components AS connected
        {where}
        ORDER BY connected.id
    """, parameters).fetchall()
    if not connected:
        return

    definition_ids = sorted({row[1] for row in connected})
    placeholders = ", ".join("?" for _ in definition_ids)
    desired_by_definition = {definition_id: set() for definition_id in definition_ids}
    for definition_id, capability_id in cur.execute(f"""
        SELECT component_definition_id, capability_id
        FROM component_capabilities
        WHERE component_definition_id IN ({placeholders})
    """, definition_ids):
        desired_by_definition[definition_id].add(capability_id)

    connected_ids = [row[0] for row in connected]
    placeholders = ", ".join("?" for _ in connected_ids)
    existing_by_component = {connected_id: [] for connected_id in connected_ids}
    for row in cur.execute(f"""
        SELECT id, connected_component_id, capability_id, lifecycle_status
        FROM component_capability_instances
        WHERE connected_component_id IN ({placeholders})
    """, connected_ids):
        existing_by_component[row[1]].append(row)

    timestamp = now_string()
    for connected_id, definition_id, lifecycle_status, parent_removed_at in connected:
        desired = desired_by_definition[definition_id]
        existing = existing_by_component[connected_id]
        active_by_capability = {row[2]: row[0] for row in existing if row[3] == "active"}
        historical_capabilities = {row[2] for row in existing}

        if lifecycle_status == "removed":
            cur.execute("""UPDATE component_capability_instances
                SET lifecycle_status = 'removed', removed_at = ?, updated_at = ?
                WHERE connected_component_id = ? AND lifecycle_status = 'active'""",
                (parent_removed_at or timestamp, timestamp, connected_id))
            if include_removed_missing:
                for capability_id in sorted(desired - historical_capabilities):
                    removed_at = parent_removed_at or timestamp
                    cur.execute("""INSERT INTO component_capability_instances
                        (capability_instance_id, connected_component_id, capability_id,
                         lifecycle_status, created_at, updated_at, removed_at)
                        VALUES (?, ?, ?, 'removed', ?, ?, ?)""",
                        (_new_capability_instance_id(cur), connected_id, capability_id,
                         removed_at, removed_at, removed_at))
            continue

        for capability_id in sorted(set(active_by_capability) - desired):
            cur.execute("""UPDATE component_capability_instances
                SET lifecycle_status = 'removed', removed_at = ?, updated_at = ?
                WHERE id = ?""", (timestamp, timestamp, active_by_capability[capability_id]))
        for capability_id in sorted(desired - set(active_by_capability)):
            cur.execute("""INSERT INTO component_capability_instances
                (capability_instance_id, connected_component_id, capability_id,
                 lifecycle_status, created_at, updated_at)
                VALUES (?, ?, ?, 'active', ?, ?)""",
                (_new_capability_instance_id(cur), connected_id, capability_id,
                 timestamp, timestamp))


def _connected_component_rows(conn, node_id, connected_component_id=None, include_removed=False):
    conn.row_factory = sqlite3.Row
    clauses, params = ["node.node_id = ?"], [node_id]
    if connected_component_id is not None:
        clauses.append("(connected.connected_component_id = ? OR connected.legacy_route_id = ?)")
        params.extend((connected_component_id, connected_component_id))
    if not include_removed:
        clauses.append("connected.lifecycle_status = 'active'")
    rows = conn.execute(f"""
        SELECT connected.id AS connected_db_id, connected.connected_component_id,
               connected.label, connected.location, connected.zone,
               connected.lifecycle_status, connected.created_at, connected.updated_at, connected.removed_at,
               node.node_id, node.name AS node_name, definition.id AS definition_db_id,
               definition.definition_key, definition.display_name, definition.manufacturer,
               definition.model, definition.component_class
        FROM connected_components AS connected
        JOIN nodes AS node ON node.id = connected.node_db_id
        JOIN component_definitions AS definition ON definition.id = connected.component_definition_id
        WHERE {' AND '.join(clauses)}
        ORDER BY connected.created_at, connected.id
    """, params).fetchall()
    results = [dict(row) | {
        "interfaces": [], "capabilities": [], "capability_instances": []
    } for row in rows]
    if not results:
        return results
    by_definition = {}
    by_connected = {}
    for item in results:
        by_connected[item["connected_db_id"]] = item
        by_definition.setdefault(item.pop("definition_db_id"), []).append(item)
    ids = list(by_definition)
    placeholders = ", ".join("?" for _ in ids)
    for definition_id, interface in conn.execute(f"""
        SELECT component_definition_id, interface_type FROM component_interface_requirements
        WHERE component_definition_id IN ({placeholders}) ORDER BY interface_type
    """, ids):
        for item in by_definition[definition_id]:
            item["interfaces"].append(interface)
    for row in conn.execute(f"""
        SELECT mapping.component_definition_id, capability.capability_key,
               capability.display_name, capability.capability_class, capability.description
        FROM component_capabilities AS mapping
        JOIN capabilities AS capability ON capability.id = mapping.capability_id
        WHERE mapping.component_definition_id IN ({placeholders}) ORDER BY capability.display_name
    """, ids):
        capability = {key: row[key] for key in ("capability_key", "display_name", "capability_class", "description")}
        for item in by_definition[row["component_definition_id"]]:
            item["capabilities"].append(capability.copy())
    connected_ids = list(by_connected)
    placeholders = ", ".join("?" for _ in connected_ids)
    for row in conn.execute(f"""
        SELECT capability_instance.connected_component_id,
               capability_instance.capability_instance_id,
               capability_instance.lifecycle_status,
               capability_instance.created_at,
               capability_instance.updated_at,
               capability_instance.removed_at,
               capability.capability_key, capability.display_name,
               capability.capability_class, capability.description
        FROM component_capability_instances AS capability_instance
        JOIN capabilities AS capability
          ON capability.id = capability_instance.capability_id
        WHERE capability_instance.connected_component_id IN ({placeholders})
        ORDER BY capability.display_name, capability_instance.id
    """, connected_ids):
        item = by_connected[row["connected_component_id"]]
        if item["lifecycle_status"] == "active" and row["lifecycle_status"] != "active":
            continue
        item["capability_instances"].append({key: row[key] for key in (
            "capability_instance_id", "capability_key", "display_name",
            "capability_class", "description", "lifecycle_status",
            "created_at", "updated_at", "removed_at",
        )})
    for item in results:
        item.pop("connected_db_id", None)
        item["definition"] = {
            "definition_key": item["definition_key"],
            "name": item["display_name"],
            "manufacturer": item["manufacturer"],
            "model": item["model"],
            "component_class": item["component_class"],
        }
    return results


def list_connected_components(node_id, include_removed=False):
    conn = get_connection()
    exists = conn.execute("SELECT 1 FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    rows = _connected_component_rows(conn, node_id, include_removed=include_removed) if exists else None
    conn.close()
    return rows


def get_connected_component(node_id, connected_component_id):
    conn = get_connection()
    rows = _connected_component_rows(
        conn, node_id, connected_component_id, include_removed=True
    )
    conn.close()
    return rows[0] if rows else None


def _validate_connected_component_metadata(values, creating=False):
    required = {"definition_key", "label"} if creating else set()
    allowed = {"definition_key", "label", "location", "zone"} if creating else {"label", "location", "zone"}
    if not isinstance(values, dict) or required - set(values) or set(values) - allowed:
        raise ValueError("Request contains unsupported or missing connected-component fields")
    result = {"location": None, "zone": None} if creating else {}
    if "definition_key" in values:
        if not isinstance(values["definition_key"], str) or not values["definition_key"]:
            raise ValueError("definition_key must be a non-empty string")
        result["definition_key"] = values["definition_key"]
    if "label" in values:
        if not isinstance(values["label"], str) or not values["label"].strip():
            raise ValueError("label must be a non-empty string")
        result["label"] = values["label"].strip()
    for field in ("location", "zone"):
        if field in values:
            result[field] = _clean_optional_text(values[field], field)
    return result


def create_connected_component(node_id, values):
    values = _validate_connected_component_metadata(values, creating=True)
    conn = get_connection()
    try:
        cur = conn.cursor()
        node = cur.execute("SELECT id FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if node is None:
            raise LookupError("Node not found")
        definition = cur.execute("""SELECT id FROM component_definitions
            WHERE definition_key = ? AND lifecycle_status = 'active'""",
            (values["definition_key"],)).fetchone()
        if definition is None:
            raise LookupError("Component definition not found")
        public_id, timestamp = _new_connected_component_id(cur), now_string()
        cur.execute("""INSERT INTO connected_components
            (connected_component_id, node_db_id, component_definition_id, label, location, zone,
             lifecycle_status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)""",
            (public_id, node[0], definition[0], values["label"], values["location"],
             values["zone"], timestamp, timestamp))
        connected_component_id = cur.lastrowid
        _reconcile_capability_instances(cur, [connected_component_id])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_connected_component(node_id, public_id)


def update_connected_component(node_id, connected_component_id, values):
    if isinstance(values, dict) and "definition_key" in values:
        raise ValueError("definition_key is immutable")
    values = _validate_connected_component_metadata(values)
    if not values:
        raise ValueError("Request body must not be empty")
    conn = get_connection()
    try:
        row = conn.execute("""SELECT connected.id, connected.lifecycle_status
            FROM connected_components AS connected JOIN nodes AS node ON node.id = connected.node_db_id
            WHERE node.node_id = ? AND (connected.connected_component_id = ? OR connected.legacy_route_id = ?)""",
            (node_id, connected_component_id, connected_component_id)).fetchone()
        if row is None:
            return None
        if row[1] != "active":
            raise ValueError("Removed connected components cannot be edited")
        values["updated_at"] = now_string()
        assignments = ", ".join(f"{key} = ?" for key in values)
        conn.execute(f"UPDATE connected_components SET {assignments} WHERE id = ?", (*values.values(), row[0]))
        conn.commit()
    finally:
        conn.close()
    return get_connected_component(node_id, connected_component_id)


def remove_connected_component(node_id, connected_component_id):
    conn = get_connection()
    try:
        timestamp = now_string()
        row = conn.execute("""SELECT connected.id
            FROM connected_components AS connected
            JOIN nodes AS node ON node.id = connected.node_db_id
            WHERE node.node_id = ?
              AND (connected.connected_component_id = ? OR connected.legacy_route_id = ?)
              AND connected.lifecycle_status = 'active'""",
            (node_id, connected_component_id, connected_component_id)).fetchone()
        if row is None:
            return False
        conn.execute("""UPDATE connected_components
            SET lifecycle_status = 'removed', removed_at = ?, updated_at = ?
            WHERE id = ?""", (timestamp, timestamp, row[0]))
        conn.execute("""UPDATE component_capability_instances
            SET lifecycle_status = 'removed', removed_at = ?, updated_at = ?
            WHERE connected_component_id = ? AND lifecycle_status = 'active'""",
            (timestamp, timestamp, row[0]))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_latest_telemetry(node_id, sensor_type):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT value FROM measurements
        WHERE node_id = ? AND sensor_type = ?
        ORDER BY timestamp DESC, id DESC LIMIT 1
        """,
        (node_id, sensor_type),
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_node_details(node_id):
    node = get_node(node_id)
    if node is None:
        return None
    status = get_node_status(node_id)
    node.update({
        "status": status["status"],
        "last_seen": status["last_update"],
        "rssi": get_latest_telemetry(node_id, "rssi"),
        "uptime_seconds": get_latest_telemetry(node_id, "uptime_seconds"),
        "capabilities": get_node_capabilities(node_id),
        "organization": get_node_organization(node_id),
    })
    node["health"] = calculate_node_health(
        node["status"], node["capabilities"]["state"]
    )
    return node


def calculate_node_health(runtime_status, capability_state):
    """Apply the shared runtime precedence used by details and fleet views."""
    if runtime_status in {"disabled", "offline", "unknown"}:
        return runtime_status
    return capability_state


def _runtime_status(enabled, latest_timestamp, offline_threshold_seconds=60):
    if not bool(enabled):
        return "disabled"
    if latest_timestamp is None:
        return "unknown"
    latest_datetime = datetime.strptime(latest_timestamp, "%Y-%m-%d %H:%M:%S")
    age_seconds = (datetime.now() - latest_datetime).total_seconds()
    return "online" if age_seconds <= offline_threshold_seconds else "offline"


def get_nodes_overview(offline_threshold_seconds=60):
    """Return compact fleet state using one connection and bounded index lookups.

    The correlated latest-timestamp lookup seeks once per registered node through
    idx_measurements_node_timestamp_id rather than grouping telemetry history.
    Capability state is calculated from the normalized expected/reported sets.
    """
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT n.id, n.node_id, n.name, n.enabled,
               (SELECT m.timestamp
                FROM measurements AS m
                WHERE m.node_id = n.node_id
                ORDER BY m.timestamp DESC, m.id DESC
                LIMIT 1) AS latest_timestamp,
               EXISTS (
                   SELECT 1 FROM node_capability_reports AS reports
                   WHERE reports.node_db_id = n.id
               ) AS has_report,
               EXISTS (
                   SELECT 1 FROM component_capability_instances AS expected
                   JOIN connected_components AS connected
                     ON connected.id = expected.connected_component_id
                   WHERE connected.node_db_id = n.id
                     AND connected.lifecycle_status = 'active'
                     AND expected.lifecycle_status = 'active'
                     AND NOT EXISTS (
                         SELECT 1 FROM node_reported_capabilities AS reported
                         WHERE reported.node_db_id = n.id
                           AND reported.capability_id = expected.capability_id
                     )
               ) AS has_missing_capability
        FROM nodes AS n
        ORDER BY n.node_id ASC
    """).fetchall()
    node_ids = [row["id"] for row in rows]
    organization = {node_db_id: {"groups": [], "tags": [], "expected_capabilities": []}
                    for node_db_id in node_ids}
    # Three bounded, indexed relationship queries avoid an overview N+1 while
    # keeping each reusable definition as structured JSON.
    for relation, table, definition, key in (
        ("groups", "node_groups", "groups", "group_id"),
        ("tags", "node_tags", "tags", "tag_id"),
    ):
        for item in conn.execute(f"""
            SELECT membership.node_db_id, definition.id, definition.name
            FROM {table} AS membership
            JOIN {definition} AS definition ON definition.id = membership.{key}
            ORDER BY definition.name COLLATE NOCASE, definition.id
        """):
            organization[item["node_db_id"]][relation].append(
                {"id": item["id"], "name": item["name"]}
            )
    for item in conn.execute("""
        SELECT DISTINCT connected.node_db_id, capability.capability_key
        FROM component_capability_instances AS expected
        JOIN connected_components AS connected
          ON connected.id = expected.connected_component_id
        JOIN capabilities AS capability ON capability.id = expected.capability_id
        WHERE connected.lifecycle_status = 'active'
          AND expected.lifecycle_status = 'active'
        ORDER BY capability.display_name
    """):
        organization[item["node_db_id"]]["expected_capabilities"].append(
            item["capability_key"]
        )
    conn.close()

    overview = []
    for row in rows:
        status = _runtime_status(
            row["enabled"], row["latest_timestamp"], offline_threshold_seconds
        )
        capability_state = (
            "unknown" if not row["has_report"] else
            "capability_mismatch" if row["has_missing_capability"] else "healthy"
        )
        overview.append({
            "node_id": row["node_id"],
            "name": row["name"],
            "status": status,
            "health": calculate_node_health(status, capability_state),
            **organization[row["id"]],
        })
    return overview


def _definition_table(kind):
    if kind not in {"group", "tag"}:
        raise ValueError("Unknown organization type")
    return f"{kind}s"


def list_definitions(kind):
    table = _definition_table(kind)
    membership = f"node_{table}"
    foreign_key = f"{kind}_id"
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"""
        SELECT definition.id, definition.name, COUNT(membership.node_db_id) AS node_count
        FROM {table} AS definition
        LEFT JOIN {membership} AS membership ON membership.{foreign_key} = definition.id
        GROUP BY definition.id, definition.name
        ORDER BY definition.name COLLATE NOCASE, definition.id
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_definition(kind, name):
    table = _definition_table(kind)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    clean_name = name.strip()
    conn = get_connection()
    try:
        cursor = conn.execute(f"INSERT INTO {table} (name) VALUES (?)", (clean_name,))
        conn.commit()
        return {"id": cursor.lastrowid, "name": clean_name, "node_count": 0}
    except sqlite3.IntegrityError as error:
        conn.rollback()
        raise ValueError(f"A {kind} with that name already exists") from error
    finally:
        conn.close()


def rename_definition(kind, definition_id, name):
    table = _definition_table(kind)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name must be a non-empty string")
    clean_name = name.strip()
    conn = get_connection()
    try:
        cursor = conn.execute(f"UPDATE {table} SET name = ? WHERE id = ?", (clean_name, definition_id))
        if cursor.rowcount == 0:
            return False
        conn.commit()
        return True
    except sqlite3.IntegrityError as error:
        conn.rollback()
        raise ValueError(f"A {kind} with that name already exists") from error
    finally:
        conn.close()


def delete_definition(kind, definition_id):
    table = _definition_table(kind)
    conn = get_connection()
    cursor = conn.execute(f"DELETE FROM {table} WHERE id = ?", (definition_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_node_organization(node_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    node = conn.execute("SELECT id FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        conn.close()
        return None
    result = {}
    for kind in ("group", "tag"):
        table = f"{kind}s"
        rows = conn.execute(f"""
            SELECT definition.id, definition.name FROM {table} AS definition
            JOIN node_{table} AS membership ON membership.{kind}_id = definition.id
            WHERE membership.node_db_id = ?
            ORDER BY definition.name COLLATE NOCASE, definition.id
        """, (node["id"],)).fetchall()
        result[table] = [dict(row) for row in rows]
    conn.close()
    return result


def mutate_organization(node_ids, kind, definition_ids, operation):
    """Atomically mutate one or many node memberships after complete validation."""
    table = _definition_table(kind)
    if operation not in {"add", "remove"}:
        raise ValueError("operation must be add or remove")
    membership = f"node_{table}"
    foreign_key = f"{kind}_id"
    node_ids = list(dict.fromkeys(node_ids))
    definition_ids = list(dict.fromkeys(definition_ids))
    conn = get_connection()
    try:
        placeholders = ", ".join("?" for _ in node_ids)
        nodes = conn.execute(
            f"SELECT id, node_id FROM nodes WHERE node_id IN ({placeholders})", node_ids
        ).fetchall()
        found_nodes = {row[1]: row[0] for row in nodes}
        missing_nodes = [node_id for node_id in node_ids if node_id not in found_nodes]
        if missing_nodes:
            raise LookupError(f"Unknown node_id(s): {', '.join(missing_nodes)}")
        placeholders = ", ".join("?" for _ in definition_ids)
        found_definitions = {row[0] for row in conn.execute(
            f"SELECT id FROM {table} WHERE id IN ({placeholders})", definition_ids
        )}
        missing_definitions = [str(item) for item in definition_ids if item not in found_definitions]
        if missing_definitions:
            raise LookupError(f"Unknown {kind} ID(s): {', '.join(missing_definitions)}")
        pairs = [(found_nodes[node_id], definition_id)
                 for node_id in node_ids for definition_id in definition_ids]
        if operation == "add":
            conn.executemany(
                f"INSERT OR IGNORE INTO {membership} (node_db_id, {foreign_key}) VALUES (?, ?)", pairs
            )
        else:
            conn.executemany(
                f"DELETE FROM {membership} WHERE node_db_id = ? AND {foreign_key} = ?", pairs
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_capabilities():
    """Return the small, system-owned capability registry."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT capability_key, display_name, capability_class, description
        FROM capabilities
        ORDER BY CASE capability_class WHEN 'sensor' THEN 1 WHEN 'actuator' THEN 2 ELSE 3 END,
                 display_name
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _validated_capability_ids(cur, capability_keys):
    keys = list(dict.fromkeys(capability_keys))
    if not keys:
        return keys, {}
    placeholders = ", ".join("?" for _ in keys)
    rows = cur.execute(
        f"SELECT id, capability_key FROM capabilities WHERE capability_key IN ({placeholders})",
        keys,
    ).fetchall()
    ids = {key: capability_id for capability_id, key in rows}
    unknown = sorted(set(keys) - set(ids))
    if unknown:
        raise ValueError(f"Unknown capability key(s): {', '.join(unknown)}")
    return keys, ids


def _validated_component_capability_ids(cur, capability_keys):
    """Validate capability mappings allowed for physical sensor/actuator definitions."""
    keys, ids = _validated_capability_ids(cur, capability_keys)
    if not keys:
        return keys, ids
    placeholders = ", ".join("?" for _ in keys)
    communication = [row[0] for row in cur.execute(f"""
        SELECT capability_key FROM capabilities
        WHERE capability_key IN ({placeholders}) AND capability_class = 'communication'
        ORDER BY display_name
    """, keys)]
    if communication:
        raise ValueError(
            "Communication capabilities such as Wi-Fi and LoRaWAN cannot be assigned "
            "to sensor/actuator component definitions"
        )
    return keys, ids


def replace_expected_capabilities(node_id, capability_keys):
    """Atomically replace server-owned expected capabilities."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        node = cur.execute("SELECT id FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
        if node is None:
            return False
        keys, ids = _validated_capability_ids(cur, capability_keys)
        cur.execute("DELETE FROM node_expected_capabilities WHERE node_db_id = ?", node)
        cur.executemany(
            "INSERT INTO node_expected_capabilities (node_db_id, capability_id) VALUES (?, ?)",
            [(node[0], ids[key]) for key in keys],
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def replace_reported_capabilities(node_id, capability_keys):
    """Atomically replace a device-owned complete capability report."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        node_db_id = get_or_create_node(cur, node_id)
        keys, ids = _validated_capability_ids(cur, capability_keys)
        reported_at = now_string()
        cur.execute("DELETE FROM node_reported_capabilities WHERE node_db_id = ?", (node_db_id,))
        cur.executemany("""
            INSERT INTO node_reported_capabilities
                (node_db_id, capability_id, reported_at) VALUES (?, ?, ?)
        """, [(node_db_id, ids[key], reported_at) for key in keys])
        cur.execute("""
            INSERT INTO node_capability_reports (node_db_id, reported_at) VALUES (?, ?)
            ON CONFLICT(node_db_id) DO UPDATE SET reported_at = excluded.reported_at
        """, (node_db_id, reported_at))
        conn.commit()
        return reported_at
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_node_capabilities(node_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    node = conn.execute("SELECT id FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
    if node is None:
        conn.close()
        return None
    definitions = {row["id"]: dict(row) for row in conn.execute("""
        SELECT id, capability_key, display_name, capability_class, description
        FROM capabilities
    """)}
    derived_rows = conn.execute("""
        SELECT capability_instance.capability_id, COUNT(*) AS instance_count
        FROM component_capability_instances AS capability_instance
        JOIN connected_components AS connected
          ON connected.id = capability_instance.connected_component_id
        WHERE connected.node_db_id = ?
          AND connected.lifecycle_status = 'active'
          AND capability_instance.lifecycle_status = 'active'
        GROUP BY capability_instance.capability_id
    """, (node[0],)).fetchall()
    expected_counts = dict(derived_rows)
    reported_ids = [row[0] for row in conn.execute(
        "SELECT capability_id FROM node_reported_capabilities WHERE node_db_id = ?", (node[0],)
    )]
    report = conn.execute(
        "SELECT reported_at FROM node_capability_reports WHERE node_db_id = ?", (node[0],)
    ).fetchone()
    conn.close()
    expected_set, reported_set = set(expected_counts), set(reported_ids)
    ordered = lambda ids: sorted((definitions[item].copy() for item in ids), key=lambda item: item["display_name"])
    expected = ordered(expected_set)
    for item in expected:
        item["count"] = expected_counts[item["id"]]
        item.pop("id", None)
    def clean(items):
        for item in items:
            item.pop("id", None)
        return items
    return {
        "expected": expected,
        "reported": clean(ordered(reported_set)),
        "missing": clean(ordered(expected_set - reported_set)) if report else [],
        "unexpected": clean(ordered(reported_set - expected_set)) if report else [],
        "state": "unknown" if report is None else (
            "capability_mismatch" if expected_set - reported_set else "healthy"
        ),
        "reported_at": report[0] if report else None,
    }


def save_measurements(node_id, readings):
    timestamp = now_string()
    saved = []

    conn = get_connection()
    cur = conn.cursor()

    node_db_id = get_or_create_node(cur, node_id)

    for sensor_type, value in readings.items():
        unit = SENSOR_UNITS.get(sensor_type)

        if unit is None:
            conn.close()
            raise ValueError(f"Unknown sensor_type: {sensor_type}")

        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            conn.close()
            raise ValueError(f"Invalid numeric value for {sensor_type}: {value}")

        cur.execute(
            """
            INSERT OR IGNORE INTO sensors
            (node_db_id, sensor_type, unit, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (node_db_id, sensor_type, unit, timestamp)
        )

        cur.execute(
            """
            INSERT INTO measurements
            (node_db_id, node_id, sensor_type, value, unit, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (node_db_id, node_id, sensor_type, numeric_value, unit, timestamp)
        )

        saved.append({
            "node_id": node_id,
            "sensor_type": sensor_type,
            "value": numeric_value,
            "unit": unit,
            "timestamp": timestamp
        })

    conn.commit()
    conn.close()

    return saved


def get_node_status(node_id, offline_threshold_seconds=60):
    conn = get_connection()
    cur = conn.cursor()

    node = cur.execute(
        "SELECT enabled FROM nodes WHERE node_id = ?", (node_id,)
    ).fetchone()
    cur.execute(
        """
        SELECT timestamp
        FROM measurements
        WHERE node_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (node_id,)
    )

    row = cur.fetchone()
    conn.close()

    latest_timestamp = row[0] if row else None
    status = _runtime_status(
        node[0] if node is not None else True,
        latest_timestamp,
        offline_threshold_seconds,
    )
    return {
        "node_id": node_id,
        "status": status,
        "last_update": latest_timestamp,
        "offline_threshold_seconds": offline_threshold_seconds
    }


def get_recent_measurements(node_id=None):
    node_id = node_id or DEFAULT_NODE_ID
    conn = get_connection()
    cur = conn.cursor()

    # Walk the newest rows for this node through the covering index and stop as
    # soon as the requested number of distinct reporting timestamps is found.
    # This avoids both a full-history GROUP BY and any fixed sensors-per-cycle
    # assumption.
    timestamp_rows = cur.execute(
        """
        SELECT timestamp
        FROM measurements
        WHERE node_id = ?
        ORDER BY timestamp DESC, id DESC
        """,
        (node_id,),
    )
    timestamps = []
    previous_timestamp = None
    for (timestamp,) in timestamp_rows:
        if timestamp == previous_timestamp:
            continue
        timestamps.append(timestamp)
        previous_timestamp = timestamp
        if len(timestamps) == READING_LIMIT:
            break

    if not timestamps:
        conn.close()
        return []

    placeholders = ", ".join("?" for _ in timestamps)
    rows = cur.execute(
        f"""
        SELECT timestamp, sensor_type, value, unit
        FROM measurements
        WHERE node_id = ? AND timestamp IN ({placeholders})
        ORDER BY timestamp ASC, id ASC
        """,
        (node_id, *timestamps),
    ).fetchall()
    conn.close()

    grouped = {}

    for timestamp, sensor_type, value, unit in rows:
        if timestamp not in grouped:
            grouped[timestamp] = {
                "timestamp": timestamp,
                "node_id": node_id
            }

        grouped[timestamp][sensor_type] = value

    return list(grouped.values())
