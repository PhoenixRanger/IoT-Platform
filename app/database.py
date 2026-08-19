import sqlite3
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
    ("wifi", "Wi-Fi", "communication", "Communicates over Wi-Fi."),
    ("lorawan", "LoRaWAN", "communication", "Communicates over LoRaWAN."),
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
        "hardware_revision": "TEXT",
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

    conn.commit()
    conn.close()


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
    "hardware_revision",
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
               hardware_revision, firmware_name, firmware_version,
               ota_hostname, created_at
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
                   SELECT 1 FROM node_expected_capabilities AS expected
                   WHERE expected.node_db_id = n.id
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
        SELECT expected.node_db_id, capability.capability_key
        FROM node_expected_capabilities AS expected
        JOIN capabilities AS capability ON capability.id = expected.capability_id
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
    expected_ids = [row[0] for row in conn.execute(
        "SELECT capability_id FROM node_expected_capabilities WHERE node_db_id = ?", (node[0],)
    )]
    reported_ids = [row[0] for row in conn.execute(
        "SELECT capability_id FROM node_reported_capabilities WHERE node_db_id = ?", (node[0],)
    )]
    report = conn.execute(
        "SELECT reported_at FROM node_capability_reports WHERE node_db_id = ?", (node[0],)
    ).fetchone()
    conn.close()
    expected_set, reported_set = set(expected_ids), set(reported_ids)
    ordered = lambda ids: sorted((definitions[item] for item in ids), key=lambda item: item["display_name"])
    return {
        "expected": ordered(expected_set),
        "reported": ordered(reported_set),
        "missing": ordered(expected_set - reported_set) if report else [],
        "unexpected": ordered(reported_set - expected_set) if report else [],
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
