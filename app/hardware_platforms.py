"""Reusable programmable-board definitions and their exposed signal resources."""
import re
import secrets
import sqlite3

from app import database

CAPABILITIES = (
    "digital_input", "digital_output", "pwm", "adc", "dac", "i2c_sda", "i2c_scl",
    "spi_mosi", "spi_miso", "spi_sck", "spi_cs", "uart_tx", "uart_rx",
)
RESOURCE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
MAX_RESOURCE_IDENTIFIER_LENGTH = 64

# These are fixed v1.17 seed reference groups, deliberately independent from
# CAPABILITIES. Expanding the global vocabulary must never mutate old boards.
_V117_OUTPUT_CAPABILITIES = frozenset({
    "digital_input", "digital_output", "pwm", "i2c_sda", "i2c_scl",
    "spi_mosi", "spi_miso", "spi_sck", "spi_cs", "uart_tx", "uart_rx",
})
_V117_INPUT_ONLY_CAPABILITIES = frozenset({
    "digital_input", "adc", "spi_miso", "uart_rx",
})
_HELTEC_NAMES = [1,2,3,4,5,6,7,19,20,26,33,34,38,39,40,41,42,45,46,47,48]
_AZ_NAMES = [0,1,2,3,4,5,12,13,14,15,16,17,18,19,21,22,23,25,26,27,32,33,34,35,36,39]
_AZ_ADC = {0,2,4,12,13,14,15,25,26,27,32,33,34,35,36,39}

def _seed_resources(names, factory):
    return [{"resource": f"GPIO{pin}", "capabilities": sorted(factory(pin))} for pin in names]


def _natural_resource_key(identifier):
    """Return a deterministic case-insensitive natural ordering key."""
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"([0-9]+)", identifier)
    )

HARDWARE_PLATFORM_SEEDS = (
    {
        "seed_key": "heltec-wifi-lora-32-v3", "display_name": "Heltec WiFi LoRa 32 V3.2",
        "manufacturer": "Heltec Automation", "model": "WiFi LoRa 32", "mcu": "ESP32-S3",
        "revision": "V3.2", "description": None,
        "resources": _seed_resources(
            _HELTEC_NAMES,
            lambda pin: _V117_OUTPUT_CAPABILITIES | ({"adc"} if pin in {
                1, 2, 3, 4, 5, 6, 7, 19, 20
            } else set()),
        ),
    },
    {
        "seed_key": "az-delivery-esp32-devkitc-v2", "display_name": "AZ-Delivery ESP32 DevKitC V2",
        "manufacturer": "AZ-Delivery", "model": "ESP32 DevKitC", "mcu": "ESP32-WROOM-32",
        "revision": "V2", "description": None,
        "resources": _seed_resources(_AZ_NAMES, lambda pin: (
            _V117_INPUT_ONLY_CAPABILITIES if pin in {34, 35, 36, 39}
            else _V117_OUTPUT_CAPABILITIES
            | ({"adc"} if pin in _AZ_ADC else set())
            | ({"dac"} if pin in {25, 26} else set())
        )),
    },
)


def _new_id(cur):
    for _ in range(12):
        value = f"hp_{secrets.token_hex(5)}"
        if cur.execute("SELECT 1 FROM hardware_platforms WHERE hardware_platform_id=?", (value,)).fetchone() is None:
            return value
    raise RuntimeError("Unable to generate a unique Hardware Platform ID")


def migrate_hardware_platforms(cur, original_node_columns):
    cur.execute("""CREATE TABLE IF NOT EXISTS hardware_platforms (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hardware_platform_id TEXT NOT NULL UNIQUE CHECK (hardware_platform_id GLOB 'hp_*'),
        seed_key TEXT UNIQUE,
        display_name TEXT NOT NULL, manufacturer TEXT NOT NULL, model TEXT NOT NULL,
        mcu TEXT NOT NULL, revision TEXT, description TEXT, first_used_at TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS hardware_platform_resources (
        id INTEGER PRIMARY KEY AUTOINCREMENT, hardware_platform_db_id INTEGER NOT NULL,
        resource_name TEXT NOT NULL, UNIQUE(hardware_platform_db_id, resource_name),
        FOREIGN KEY(hardware_platform_db_id) REFERENCES hardware_platforms(id) ON DELETE CASCADE)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS hardware_resource_capabilities (
        hardware_resource_id INTEGER NOT NULL, capability TEXT NOT NULL,
        PRIMARY KEY(hardware_resource_id, capability),
        FOREIGN KEY(hardware_resource_id) REFERENCES hardware_platform_resources(id) ON DELETE CASCADE)""")
    if "hardware_platform_id" not in original_node_columns:
        cur.execute("ALTER TABLE nodes ADD COLUMN hardware_platform_id TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_hardware_resources_platform ON hardware_platform_resources(hardware_platform_db_id, id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_hardware_platform ON nodes(hardware_platform_id)")
    for seed in HARDWARE_PLATFORM_SEEDS:
        row = cur.execute("SELECT id FROM hardware_platforms WHERE seed_key=?", (seed["seed_key"],)).fetchone()
        if row is None:
            timestamp = database.now_string()
            public_id = _new_id(cur)
            cur.execute("""INSERT INTO hardware_platforms
                (hardware_platform_id,seed_key,display_name,manufacturer,model,mcu,revision,description,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""", (public_id, seed["seed_key"], seed["display_name"], seed["manufacturer"], seed["model"], seed["mcu"], seed["revision"], seed["description"], timestamp, timestamp))
            _replace_resources(cur, cur.lastrowid, seed["resources"])
    aliases = {"heltec-wifi-lora-32-v3": "heltec-wifi-lora-32-v3", "az-delivery-esp32-devkitc-v2": "az-delivery-esp32-devkitc-v2"}
    for alias, seed_key in aliases.items():
        platform_id = cur.execute("SELECT hardware_platform_id FROM hardware_platforms WHERE seed_key=?", (seed_key,)).fetchone()[0]
        cur.execute("UPDATE nodes SET hardware_platform_id=? WHERE hardware_platform_id IS NULL AND hardware_model=?", (platform_id, alias))
    cur.execute("""UPDATE hardware_platforms SET first_used_at=COALESCE(first_used_at, ?)
        WHERE first_used_at IS NULL AND hardware_platform_id IN
        (SELECT hardware_platform_id FROM nodes WHERE hardware_platform_id IS NOT NULL)""", (database.now_string(),))


def _validate(values, creating=False):
    required = {"display_name","manufacturer","model","mcu","resources"} if creating else set()
    allowed = {"display_name","manufacturer","model","mcu","revision","description","resources"}
    if not isinstance(values, dict) or required-set(values) or set(values)-allowed:
        raise ValueError("A valid Hardware Platform definition is required")
    result = {}
    for field in ("display_name","manufacturer","model","mcu"):
        if field in values:
            if not isinstance(values[field], str) or not values[field].strip(): raise ValueError(f"{field} must be a non-empty string")
            result[field] = values[field].strip()
    for field in ("revision","description"):
        if field in values:
            result[field] = database._clean_optional_text(values[field], field)
    if "resources" in values:
        if not isinstance(values["resources"], list): raise ValueError("resources must be a list")
        seen=set(); resources=[]
        for item in values["resources"]:
            if not isinstance(item, dict) or set(item)!={"resource","capabilities"}: raise ValueError("Each resource requires resource and capabilities")
            name=item["resource"]
            caps=item["capabilities"]
            if not isinstance(name, str):
                raise ValueError("Resource identifiers must be strings")
            name = name.strip()
            if (not name or len(name) > MAX_RESOURCE_IDENTIFIER_LENGTH
                    or not RESOURCE_PATTERN.fullmatch(name)):
                raise ValueError(
                    "Resource identifiers must use a valid board-level signal label, "
                    "for example GPIO21, PA9, D13, or A0"
                )
            if name in seen: raise ValueError("Duplicate resources are not allowed")
            if not isinstance(caps,list) or any(not isinstance(x,str) for x in caps) or len(caps)!=len(set(caps)): raise ValueError("Resource capabilities must be a unique list")
            unknown=set(caps)-set(CAPABILITIES)
            if unknown: raise ValueError(f"Unknown resource capability(s): {', '.join(sorted(unknown))}")
            seen.add(name); resources.append({"resource":name,"capabilities":caps})
        result["resources"]=resources
    return result


def _replace_resources(cur, platform_db_id, resources):
    cur.execute("DELETE FROM hardware_platform_resources WHERE hardware_platform_db_id=?", (platform_db_id,))
    for item in resources:
        cur.execute("INSERT INTO hardware_platform_resources(hardware_platform_db_id,resource_name) VALUES(?,?)", (platform_db_id,item["resource"]))
        rid=cur.lastrowid
        cur.executemany("INSERT INTO hardware_resource_capabilities(hardware_resource_id,capability) VALUES(?,?)", [(rid,c) for c in item["capabilities"]])


def _rows(conn, public_id=None):
    conn.row_factory=sqlite3.Row
    where="WHERE p.hardware_platform_id=?" if public_id else ""
    rows=conn.execute(f"""SELECT p.*, COUNT(n.id) active_node_count FROM hardware_platforms p
        LEFT JOIN nodes n ON n.hardware_platform_id=p.hardware_platform_id {where}
        GROUP BY p.id ORDER BY p.display_name COLLATE NOCASE,p.hardware_platform_id""", (public_id,) if public_id else ()).fetchall()
    result=[]
    by_database_id = {}
    for row in rows:
        item={k:row[k] for k in ("hardware_platform_id","display_name","manufacturer","model","mcu","revision","description","created_at","updated_at","first_used_at","active_node_count")}
        item["technical_locked"]=row["first_used_at"] is not None; item["resources"]=[]
        by_database_id[row["id"]] = item
        result.append(item)
    if not rows:
        return result
    placeholders = ",".join("?" for _ in rows)
    resources = conn.execute(f"""SELECT r.id,r.hardware_platform_db_id,r.resource_name
        FROM hardware_platform_resources r WHERE r.hardware_platform_db_id IN ({placeholders})
        ORDER BY r.hardware_platform_db_id,r.resource_name COLLATE NOCASE,r.resource_name""",
        [row["id"] for row in rows]).fetchall()
    capabilities = {resource["id"]: [] for resource in resources}
    if resources:
        resource_placeholders = ",".join("?" for _ in resources)
        for capability in conn.execute(f"""SELECT hardware_resource_id,capability
            FROM hardware_resource_capabilities
            WHERE hardware_resource_id IN ({resource_placeholders})
            ORDER BY hardware_resource_id,capability""", [resource["id"] for resource in resources]):
            capabilities[capability["hardware_resource_id"]].append(capability["capability"])
    for resource in resources:
        by_database_id[resource["hardware_platform_db_id"]]["resources"].append({
            "resource": resource["resource_name"],
            "capabilities": capabilities[resource["id"]],
        })
    for item in result:
        item["resources"].sort(key=lambda resource: _natural_resource_key(resource["resource"]))
    return result


def list_hardware_platforms():
    conn=database.get_connection(); result=_rows(conn); conn.close(); return result

def get_hardware_platform(public_id):
    conn=database.get_connection(); rows=_rows(conn,public_id); conn.close(); return rows[0] if rows else None

def create_hardware_platform(values):
    values=_validate(values,True); conn=database.get_connection()
    try:
        cur=conn.cursor(); public_id=_new_id(cur); timestamp=database.now_string(); resources=values.pop("resources")
        cur.execute("""INSERT INTO hardware_platforms(hardware_platform_id,display_name,manufacturer,model,mcu,revision,description,created_at,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?)""",(public_id,values["display_name"],values["manufacturer"],values["model"],values["mcu"],values.get("revision"),values.get("description"),timestamp,timestamp))
        _replace_resources(cur,cur.lastrowid,resources); conn.commit()
    finally: conn.close()
    return get_hardware_platform(public_id)

def update_hardware_platform(public_id, values):
    values=_validate(values); conn=database.get_connection()
    try:
        row=conn.execute("SELECT id,first_used_at FROM hardware_platforms WHERE hardware_platform_id=?",(public_id,)).fetchone()
        if row is None: return None
        if row[1] is not None and set(values)-{"display_name","description"}: raise ValueError("Technical fields are permanently locked after first Node assignment")
        resources=values.pop("resources",None)
        if values:
            assignments=", ".join(f"{k}=?" for k in values); conn.execute(f"UPDATE hardware_platforms SET {assignments},updated_at=? WHERE id=?",(*values.values(),database.now_string(),row[0]))
        if resources is not None: _replace_resources(conn.cursor(),row[0],resources)
        conn.commit()
    finally: conn.close()
    return get_hardware_platform(public_id)

def delete_hardware_platform(public_id):
    conn=database.get_connection()
    try:
        row=conn.execute("SELECT id,first_used_at FROM hardware_platforms WHERE hardware_platform_id=?",(public_id,)).fetchone()
        if row is None:return None
        if row[1] is not None: return False
        conn.execute("DELETE FROM hardware_platforms WHERE id=?",(row[0],));conn.commit();return True
    finally:conn.close()

def assign_hardware_platform(node_id, public_id):
    conn=database.get_connection()
    try:
        node=conn.execute("SELECT hardware_platform_id FROM nodes WHERE node_id=?",(node_id,)).fetchone()
        if node is None: raise LookupError("Node not found")
        if conn.execute("SELECT 1 FROM hardware_platforms WHERE hardware_platform_id=?",(public_id,)).fetchone() is None: raise LookupError("Hardware Platform not found")
        if node[0] is not None and node[0]!=public_id: raise ValueError("A Node's Hardware Platform cannot be reassigned")
        timestamp=database.now_string()
        conn.execute("UPDATE nodes SET hardware_platform_id=? WHERE node_id=?",(public_id,node_id))
        conn.execute("UPDATE hardware_platforms SET first_used_at=COALESCE(first_used_at,?) WHERE hardware_platform_id=?",(timestamp,public_id));conn.commit()
    finally:conn.close()
    return database.get_node(node_id)
