"""Server-owned Connected Component runtime configuration.

This module is the domain boundary for configuration consumers.  Callers use
the canonical dictionaries returned here rather than depending on the SQLite
representation; transport and firmware application are deliberately absent.
"""

import sqlite3

from app import database


RUNTIME_SETTING_DEFINITIONS = ({
    "setting_key": "measurement_interval",
    "display_name": "Measurement Interval",
    "description": "Interval between requested measurement cycles for the Connected Component.",
    "value_type": "integer",
    "unit": "seconds",
    "minimum": 1,
    "maximum": 86400,
    "default_value": 60,
},)

MEASUREMENT_COMPONENT_KEYS = (
    "te-ms8607",
    "aosong-dht22",
    "generic-analog-soil-moisture-sensor",
    # Explicit compatibility targets from the pre-v1.19 deployment.  These
    # stable identities are a bounded platform migration, not inference.
    "ms8607xx",
    "def_31ead969f7",
)


class RuntimeConfigurationValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(errors[0]["message"] if errors else "Runtime configuration is invalid")


def migrate(cur):
    """Add the small relational runtime model and apply idempotent seed policy."""
    columns = {row[1] for row in cur.execute("PRAGMA table_info(connected_components)")}
    if "configured_enabled" not in columns:
        cur.execute("""ALTER TABLE connected_components
                       ADD COLUMN configured_enabled INTEGER NOT NULL DEFAULT 1""")
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS runtime_setting_definitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            setting_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            description TEXT NOT NULL,
            value_type TEXT NOT NULL CHECK (value_type IN ('integer')),
            unit TEXT,
            minimum_integer INTEGER,
            maximum_integer INTEGER,
            default_integer INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS component_definition_runtime_settings (
            component_definition_id INTEGER NOT NULL,
            runtime_setting_definition_id INTEGER NOT NULL,
            PRIMARY KEY (component_definition_id, runtime_setting_definition_id),
            FOREIGN KEY (component_definition_id) REFERENCES component_definitions(id) ON DELETE CASCADE,
            FOREIGN KEY (runtime_setting_definition_id) REFERENCES runtime_setting_definitions(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS connected_component_runtime_setting_values (
            connected_component_id INTEGER NOT NULL,
            runtime_setting_definition_id INTEGER NOT NULL,
            integer_value INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (connected_component_id, runtime_setting_definition_id),
            FOREIGN KEY (connected_component_id) REFERENCES connected_components(id) ON DELETE RESTRICT,
            FOREIGN KEY (runtime_setting_definition_id) REFERENCES runtime_setting_definitions(id) ON DELETE RESTRICT
        );
        CREATE TABLE IF NOT EXISTS node_runtime_configuration_revisions (
            node_db_id INTEGER PRIMARY KEY,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            updated_at TEXT,
            FOREIGN KEY (node_db_id) REFERENCES nodes(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_definition_runtime_settings_setting
            ON component_definition_runtime_settings(runtime_setting_definition_id, component_definition_id);
        CREATE INDEX IF NOT EXISTS idx_component_runtime_values_setting
            ON connected_component_runtime_setting_values(runtime_setting_definition_id, connected_component_id);
    """)
    for item in RUNTIME_SETTING_DEFINITIONS:
        cur.execute("""INSERT INTO runtime_setting_definitions
            (setting_key,display_name,description,value_type,unit,minimum_integer,
             maximum_integer,default_integer) VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(setting_key) DO UPDATE SET display_name=excluded.display_name,
              description=excluded.description,value_type=excluded.value_type,unit=excluded.unit,
              minimum_integer=excluded.minimum_integer,maximum_integer=excluded.maximum_integer,
              default_integer=excluded.default_integer""", tuple(item.values()))
    setting_id = cur.execute("""SELECT id FROM runtime_setting_definitions
        WHERE setting_key='measurement_interval'""").fetchone()[0]
    cur.execute(f"""INSERT OR IGNORE INTO component_definition_runtime_settings
        (component_definition_id,runtime_setting_definition_id)
        SELECT id, ? FROM component_definitions
        WHERE definition_key IN ({','.join('?' for _ in MEASUREMENT_COMPONENT_KEYS)})""",
        (setting_id, *MEASUREMENT_COMPONENT_KEYS))
    cur.execute("""DELETE FROM component_definition_runtime_settings
        WHERE component_definition_id=(SELECT id FROM component_definitions
          WHERE definition_key='generic-mosfet-switch-module')
          AND runtime_setting_definition_id=?""", (setting_id,))


def _metadata(row):
    return {
        "setting_key": row["setting_key"], "display_name": row["display_name"],
        "description": row["description"], "value_type": row["value_type"],
        "unit": row["unit"], "minimum": row["minimum_integer"],
        "maximum": row["maximum_integer"], "default_value": row["default_integer"],
    }


def list_runtime_settings():
    conn = database.get_connection(); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM runtime_setting_definitions ORDER BY setting_key").fetchall()
    conn.close()
    return [_metadata(row) for row in rows]


def definition_runtime_settings(definition_key):
    conn = database.get_connection(); conn.row_factory = sqlite3.Row
    exists = conn.execute("SELECT 1 FROM component_definitions WHERE definition_key=?", (definition_key,)).fetchone()
    rows = conn.execute("""SELECT setting.* FROM runtime_setting_definitions setting
        JOIN component_definition_runtime_settings supported
          ON supported.runtime_setting_definition_id=setting.id
        JOIN component_definitions definition ON definition.id=supported.component_definition_id
        WHERE definition.definition_key=? ORDER BY setting.setting_key""", (definition_key,)).fetchall()
    conn.close()
    return None if exists is None else [_metadata(row) for row in rows]


def replace_definition_runtime_settings(definition_key, setting_keys):
    if not isinstance(setting_keys, list) or any(not isinstance(key, str) for key in setting_keys):
        raise ValueError("runtime_settings must be a list of registered setting keys")
    if len(setting_keys) != len(set(setting_keys)):
        raise ValueError("Duplicate runtime settings are not allowed")
    conn = database.get_connection()
    try:
        row = conn.execute("""SELECT id FROM component_definitions
            WHERE definition_key=? AND lifecycle_status='active'""", (definition_key,)).fetchone()
        if row is None:
            return None
        if conn.execute("SELECT 1 FROM connected_components WHERE component_definition_id=? LIMIT 1", row).fetchone():
            raise ValueError("Supported Runtime Settings are permanently locked after first Connected Component use")
        ids = dict(conn.execute("SELECT setting_key,id FROM runtime_setting_definitions").fetchall())
        unknown = sorted(set(setting_keys) - set(ids))
        if unknown:
            raise ValueError(f"Unknown Runtime Setting(s): {', '.join(unknown)}")
        conn.execute("DELETE FROM component_definition_runtime_settings WHERE component_definition_id=?", row)
        conn.executemany("INSERT INTO component_definition_runtime_settings VALUES (?,?)",
                         [(row[0], ids[key]) for key in setting_keys])
        conn.execute("UPDATE component_definitions SET updated_at=? WHERE id=?", (database.now_string(), row[0]))
        conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return definition_runtime_settings(definition_key)


def get_node_runtime_configuration(node_id):
    conn = database.get_connection(); conn.row_factory = sqlite3.Row
    node = conn.execute("SELECT id FROM nodes WHERE node_id=?", (node_id,)).fetchone()
    if node is None:
        conn.close(); return None
    revision = conn.execute("SELECT revision FROM node_runtime_configuration_revisions WHERE node_db_id=?", (node["id"],)).fetchone()
    component_rows = conn.execute("""SELECT connected.id,connected.connected_component_id,
          connected.label,connected.configured_enabled,definition.display_name,
          definition.definition_key
        FROM connected_components connected JOIN component_definitions definition
          ON definition.id=connected.component_definition_id
        WHERE connected.node_db_id=? AND connected.lifecycle_status='active'
        ORDER BY connected.created_at,connected.id""", (node["id"],)).fetchall()
    result = {row["id"]: {
        "connected_component_id": row["connected_component_id"], "label": row["label"],
        "component_definition": {"definition_key": row["definition_key"], "display_name": row["display_name"]},
        "enabled": bool(row["configured_enabled"]), "settings": {}
    } for row in component_rows}
    if result:
        placeholders = ",".join("?" for _ in result)
        settings = conn.execute(f"""SELECT connected.id connected_id,setting.*,
              value.integer_value explicit_value
            FROM connected_components connected
            JOIN component_definition_runtime_settings supported
              ON supported.component_definition_id=connected.component_definition_id
            JOIN runtime_setting_definitions setting ON setting.id=supported.runtime_setting_definition_id
            LEFT JOIN connected_component_runtime_setting_values value
              ON value.connected_component_id=connected.id
             AND value.runtime_setting_definition_id=setting.id
            WHERE connected.id IN ({placeholders}) ORDER BY setting.setting_key""", tuple(result)).fetchall()
        for row in settings:
            explicit = row["explicit_value"]
            result[row["connected_id"]]["settings"][row["setting_key"]] = {
                **_metadata(row), "explicit_value": explicit,
                "effective_value": row["default_integer"] if explicit is None else explicit,
                "uses_default": explicit is None,
            }
    conn.close()
    return {"node_id": node_id, "runtime_configuration_revision": revision[0] if revision else 0,
            "components": list(result.values())}


def update_component_runtime_configuration(node_id, public_id, payload):
    errors = []
    if not isinstance(payload, dict) or set(payload) != {"enabled", "settings"}:
        raise RuntimeConfigurationValidationError([{"field": "request", "code": "malformed_request",
            "message": "Request must contain only enabled and settings"}])
    if not isinstance(payload["enabled"], bool):
        errors.append({"field": "enabled", "code": "invalid_type", "message": "enabled must be a boolean"})
    if not isinstance(payload["settings"], dict):
        errors.append({"field": "settings", "code": "invalid_type", "message": "settings must be an object"})
    if errors:
        raise RuntimeConfigurationValidationError(errors)
    conn = database.get_connection(); conn.row_factory = sqlite3.Row
    try:
        component = conn.execute("""SELECT connected.id,connected.node_db_id,
                connected.component_definition_id,connected.configured_enabled
            FROM connected_components connected JOIN nodes node ON node.id=connected.node_db_id
            WHERE node.node_id=? AND connected.connected_component_id=?
              AND connected.lifecycle_status='active'""", (node_id, public_id)).fetchone()
        if component is None:
            node_exists = conn.execute("SELECT 1 FROM nodes WHERE node_id=?", (node_id,)).fetchone()
            raise LookupError("Connected component not found" if node_exists else "Node not found")
        supported = {row["setting_key"]: row for row in conn.execute("""SELECT setting.*
            FROM runtime_setting_definitions setting JOIN component_definition_runtime_settings supported
              ON supported.runtime_setting_definition_id=setting.id
            WHERE supported.component_definition_id=?""", (component["component_definition_id"],))}
        registered = {row[0] for row in conn.execute(
            "SELECT setting_key FROM runtime_setting_definitions"
        )}
        for key, value in payload["settings"].items():
            if key not in supported:
                unknown = key not in registered
                errors.append({"field": f"settings.{key}",
                               "code": "unknown_setting" if unknown else "unsupported_setting",
                               "message": (f"Unknown Runtime Setting '{key}'" if unknown else
                                           f"Runtime Setting '{key}' is not supported by this Component Definition")})
                continue
            setting = supported[key]
            if isinstance(value, bool) or not isinstance(value, int):
                errors.append({"field": f"settings.{key}", "code": "invalid_type", "message": f"{key} must be an integer"})
            elif value < setting["minimum_integer"] or value > setting["maximum_integer"]:
                errors.append({"field": f"settings.{key}", "code": "out_of_range",
                               "message": f"{key} must be between {setting['minimum_integer']} and {setting['maximum_integer']}"})
        if errors:
            raise RuntimeConfigurationValidationError(errors)
        existing = dict(conn.execute("""SELECT setting.setting_key,value.integer_value
            FROM connected_component_runtime_setting_values value
            JOIN runtime_setting_definitions setting ON setting.id=value.runtime_setting_definition_id
            WHERE value.connected_component_id=?""", (component["id"],)).fetchall())
        changed = bool(component["configured_enabled"] != int(payload["enabled"])) or any(
            existing.get(key, supported[key]["default_integer"]) != value
            or (key in existing and value == supported[key]["default_integer"])
            for key, value in payload["settings"].items())
        if changed:
            conn.execute("UPDATE connected_components SET configured_enabled=?,updated_at=? WHERE id=?",
                         (int(payload["enabled"]), database.now_string(), component["id"]))
            for key, value in payload["settings"].items():
                setting = supported[key]
                if value == setting["default_integer"]:
                    conn.execute("""DELETE FROM connected_component_runtime_setting_values
                        WHERE connected_component_id=? AND runtime_setting_definition_id=?""", (component["id"], setting["id"]))
                else:
                    conn.execute("""INSERT INTO connected_component_runtime_setting_values
                        (connected_component_id,runtime_setting_definition_id,integer_value,updated_at)
                        VALUES (?,?,?,?) ON CONFLICT(connected_component_id,runtime_setting_definition_id)
                        DO UPDATE SET integer_value=excluded.integer_value,updated_at=excluded.updated_at""",
                        (component["id"], setting["id"], value, database.now_string()))
            conn.execute("""INSERT INTO node_runtime_configuration_revisions(node_db_id,revision,updated_at)
                VALUES (?,1,?) ON CONFLICT(node_db_id) DO UPDATE
                SET revision=revision+1,updated_at=excluded.updated_at""", (component["node_db_id"], database.now_string()))
            conn.commit()
        configuration = get_node_runtime_configuration(node_id)
        return next(item for item in configuration["components"] if item["connected_component_id"] == public_id) | {
            "runtime_configuration_revision": configuration["runtime_configuration_revision"], "changed": changed}
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
