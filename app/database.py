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

    # SQLite installations created before v1.10.0 have the original nodes
    # table. Add remote-management fields in place so sensor.db is preserved.
    existing_columns = {
        row[1] for row in cur.execute("PRAGMA table_info(nodes)").fetchall()
    }
    for column in (
        "hardware_model",
        "hardware_revision",
        "firmware_name",
        "firmware_version",
        "ota_hostname",
    ):
        if column not in existing_columns:
            cur.execute(f"ALTER TABLE nodes ADD COLUMN {column} TEXT")

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
        SELECT node_id, name, location, node_type, created_at
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
            "node_type": row[3],
            "created_at": row[4]
        }
        for row in rows
    ]


NODE_METADATA_FIELDS = (
    "name",
    "location",
    "node_type",
    "hardware_model",
    "hardware_revision",
    "firmware_name",
    "firmware_version",
    "ota_hostname",
)


def update_node_metadata(node_id, metadata):
    """Create a node if needed and update only metadata explicitly reported."""
    values = {key: metadata[key] for key in NODE_METADATA_FIELDS if key in metadata}
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


def get_node(node_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        """
        SELECT node_id, name, location, node_type, hardware_model,
               hardware_revision, firmware_name, firmware_version,
               ota_hostname, created_at
        FROM nodes WHERE node_id = ?
        """,
        (node_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_telemetry(node_id, sensor_type):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT value FROM measurements
        WHERE node_id = ? AND sensor_type = ?
        ORDER BY id DESC LIMIT 1
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
    })
    return node


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

    cur.execute(
        """
        SELECT timestamp
        FROM measurements
        WHERE node_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (node_id,)
    )

    row = cur.fetchone()
    conn.close()

    if row is None:
        return {
            "node_id": node_id,
            "status": "unknown",
            "last_update": None,
            "offline_threshold_seconds": offline_threshold_seconds
        }

    latest_timestamp = row[0]
    latest_datetime = datetime.strptime(latest_timestamp, "%Y-%m-%d %H:%M:%S")
    age_seconds = (datetime.now() - latest_datetime).total_seconds()
    status = "online" if age_seconds <= offline_threshold_seconds else "offline"

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

    cur.execute(
        """
        SELECT timestamp, sensor_type, value, unit
        FROM measurements
        WHERE node_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (node_id, READING_LIMIT * 4)
    )

    rows = cur.fetchall()
    conn.close()

    rows.reverse()

    grouped = {}

    for timestamp, sensor_type, value, unit in rows:
        if timestamp not in grouped:
            grouped[timestamp] = {
                "timestamp": timestamp,
                "node_id": node_id
            }

        grouped[timestamp][sensor_type] = value

    return list(grouped.values())[-READING_LIMIT:]
