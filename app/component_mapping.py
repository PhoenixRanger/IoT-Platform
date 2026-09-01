"""Reusable component endpoints and node-specific hardware mappings."""
import re
import sqlite3

from app import database


PROTOCOLS = {
    "i2c": (("sda", "SDA", "i2c_sda"), ("scl", "SCL", "i2c_scl")),
    "spi": (("mosi", "MOSI", "spi_mosi"), ("miso", "MISO", "spi_miso"),
            ("sck", "SCK", "spi_sck"), ("cs", "CS", "spi_cs")),
    "uart": (("tx", "TX", "uart_tx"), ("rx", "RX", "uart_rx")),
}
DIRECT_SIGNALS = {
    "analog_input": ("Analog Input to Node", ("adc",)),
    "analog_output": ("Analog Output from Node", ("dac",)),
    "digital_input": ("Digital Input to Node", ("digital_input",)),
    "digital_output": ("Digital Output from Node", ("digital_output",)),
    "digital_io": ("Digital I/O", ("digital_input", "digital_output")),
    "pwm_output": ("PWM Output from Node", ("pwm",)),
}
CAPABILITY_LABELS = {
    "digital_input": "Digital In", "digital_output": "Digital Out", "pwm": "PWM Out",
    "adc": "ADC", "dac": "DAC", "i2c_sda": "I²C SDA", "i2c_scl": "I²C SCL",
    "spi_mosi": "SPI MOSI", "spi_miso": "SPI MISO", "spi_sck": "SPI SCK",
    "spi_cs": "SPI CS", "uart_tx": "UART TX", "uart_rx": "UART RX",
}
SHAREABLE_ROLES = {
    frozenset({"i2c_sda"}), frozenset({"i2c_scl"}),
    frozenset({"spi_mosi"}), frozenset({"spi_miso"}),
    frozenset({"spi_sck"}),
}
PROTOCOL_ROLE_LABELS = {
    frozenset({capability}): CAPABILITY_LABELS[capability]
    for endpoints in PROTOCOLS.values()
    for _, _, capability in endpoints
}
ADDRESS_RE = re.compile(r"^0[xX]([0-9a-fA-F]{1,2})$")


class MappingValidationError(ValueError):
    def __init__(self, errors):
        super().__init__(errors[0]["message"] if errors else "Invalid hardware mapping")
        self.errors = errors


def normalize_address(value):
    if not isinstance(value, str) or not (match := ADDRESS_RE.fullmatch(value.strip())):
        raise ValueError("I²C addresses must use hexadecimal notation, for example 0x40")
    address = int(match.group(1), 16)
    if not 0x08 <= address <= 0x77:
        raise ValueError(
            "I²C peripheral address must be in the usable 7-bit range 0x08–0x77"
        )
    return f"0x{address:02X}"


def endpoint_key(label):
    key = re.sub(r"[^a-z0-9]+", "-", label.strip().casefold()).strip("-")
    if not key:
        raise ValueError("Endpoint label must contain a letter or number")
    return key


def validate_interfaces(value):
    if not isinstance(value, list) or not value:
        raise ValueError("A component definition must have at least one Interface or Direct Signal")
    result, interface_keys, direct_keys = [], set(), set()
    counts = {key: 0 for key in PROTOCOLS}
    for item in value:
        if not isinstance(item, dict) or item.get("kind") not in {"protocol", "direct_signal"}:
            raise ValueError("Each Interface or Signal must be a valid object")
        if item["kind"] == "protocol":
            allowed = {"kind", "protocol", "interface_key", "endpoints", "i2c_address_options"}
            if set(item) - allowed or item.get("protocol") not in PROTOCOLS:
                raise ValueError("Protocol must be i2c, spi, or uart")
            protocol = item["protocol"]
            counts[protocol] += 1
            generated = f"{protocol}-{counts[protocol]}"
            key = item.get("interface_key") or generated
            if key != generated or key in interface_keys:
                raise ValueError("Interface keys must be stable generated protocol identities")
            selected = item.get("endpoints", [row[0] for row in PROTOCOLS[protocol]])
            if not isinstance(selected, list) or len(selected) != len(set(selected)):
                raise ValueError("Protocol endpoints must be a unique list")
            canonical = {row[0]: row for row in PROTOCOLS[protocol]}
            if set(selected) - set(canonical) or not selected:
                raise ValueError("Protocol contains unsupported or no endpoints")
            if protocol == "i2c" and set(selected) != {"sda", "scl"}:
                raise ValueError("I²C interfaces require both SDA and SCL")
            options = item.get("i2c_address_options", [])
            if protocol != "i2c" and options:
                raise ValueError("Only I²C interfaces support address options")
            if not isinstance(options, list):
                raise ValueError("I²C address options must be a list")
            options = [normalize_address(address) for address in options]
            if len(options) != len(set(options)):
                raise ValueError("Duplicate I²C address options are not allowed")
            result.append({"kind": "protocol", "protocol": protocol, "interface_key": key,
                           "endpoints": selected, "i2c_address_options": options})
            interface_keys.add(key)
        else:
            allowed = {"kind", "signal_type", "endpoint_label", "endpoint_key", "optional"}
            if set(item) - allowed or item.get("signal_type") not in DIRECT_SIGNALS:
                raise ValueError("Direct Signal type is not supported")
            label = item.get("endpoint_label")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("Direct Signal endpoint label is required")
            key = item.get("endpoint_key") or endpoint_key(label)
            if key != endpoint_key(label):
                raise ValueError("Direct Signal endpoint key must match its stable label key")
            if key in direct_keys:
                raise ValueError("Direct Signal endpoint labels must be unique")
            if not isinstance(item.get("optional", False), bool):
                raise ValueError("Optional signal must be boolean")
            result.append({"kind": "direct_signal", "signal_type": item["signal_type"],
                           "endpoint_key": key, "endpoint_label": label.strip(),
                           "optional": item.get("optional", False)})
            direct_keys.add(key)
    return result


def migrate(cur):
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS component_interfaces (
            id INTEGER PRIMARY KEY AUTOINCREMENT, component_definition_id INTEGER NOT NULL,
            interface_key TEXT NOT NULL, interface_type TEXT NOT NULL,
            sequence INTEGER NOT NULL, UNIQUE(component_definition_id, interface_key),
            FOREIGN KEY(component_definition_id) REFERENCES component_definitions(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS component_endpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, component_definition_id INTEGER NOT NULL,
            component_interface_id INTEGER, endpoint_key TEXT NOT NULL, endpoint_label TEXT NOT NULL,
            required INTEGER NOT NULL DEFAULT 1, direct_signal_type TEXT, sequence INTEGER NOT NULL,
            FOREIGN KEY(component_definition_id) REFERENCES component_definitions(id) ON DELETE CASCADE,
            FOREIGN KEY(component_interface_id) REFERENCES component_interfaces(id) ON DELETE CASCADE);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_protocol_endpoint_identity
            ON component_endpoints(component_interface_id, endpoint_key) WHERE component_interface_id IS NOT NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_direct_endpoint_identity
            ON component_endpoints(component_definition_id, endpoint_key) WHERE component_interface_id IS NULL;
        CREATE TABLE IF NOT EXISTS endpoint_required_capabilities (
            endpoint_id INTEGER NOT NULL, capability TEXT NOT NULL,
            PRIMARY KEY(endpoint_id, capability),
            FOREIGN KEY(endpoint_id) REFERENCES component_endpoints(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS component_i2c_address_options (
            component_interface_id INTEGER NOT NULL, address INTEGER NOT NULL CHECK(address BETWEEN 0 AND 127),
            PRIMARY KEY(component_interface_id, address),
            FOREIGN KEY(component_interface_id) REFERENCES component_interfaces(id) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS connected_component_hardware_mappings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, connected_component_id INTEGER NOT NULL,
            endpoint_id INTEGER NOT NULL, hardware_resource_id INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, removed_at TEXT,
            FOREIGN KEY(connected_component_id) REFERENCES connected_components(id) ON DELETE RESTRICT,
            FOREIGN KEY(endpoint_id) REFERENCES component_endpoints(id) ON DELETE RESTRICT,
            FOREIGN KEY(hardware_resource_id) REFERENCES hardware_platform_resources(id) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS connected_component_interface_configuration (
            connected_component_id INTEGER NOT NULL, component_interface_id INTEGER NOT NULL,
            i2c_address INTEGER, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, removed_at TEXT,
            FOREIGN KEY(connected_component_id) REFERENCES connected_components(id) ON DELETE RESTRICT,
            FOREIGN KEY(component_interface_id) REFERENCES component_interfaces(id) ON DELETE RESTRICT);
        CREATE INDEX IF NOT EXISTS idx_component_interfaces_definition_v118 ON component_interfaces(component_definition_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_component_endpoints_interface ON component_endpoints(component_interface_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_component_endpoints_definition ON component_endpoints(component_definition_id, sequence);
        CREATE INDEX IF NOT EXISTS idx_mapping_component_active ON connected_component_hardware_mappings(connected_component_id, active);
        CREATE INDEX IF NOT EXISTS idx_mapping_resource_active ON connected_component_hardware_mappings(hardware_resource_id, active);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_mapping_endpoint
            ON connected_component_hardware_mappings(connected_component_id,endpoint_id) WHERE active=1;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_active_interface_configuration
            ON connected_component_interface_configuration(connected_component_id,component_interface_id) WHERE active=1;
    """)
    legacy = cur.execute("""SELECT d.id,d.definition_key,r.interface_type FROM component_definitions d
        JOIN component_interface_requirements r ON r.component_definition_id=d.id
        WHERE NOT EXISTS(SELECT 1 FROM component_interfaces i WHERE i.component_definition_id=d.id)
          AND NOT EXISTS(SELECT 1 FROM component_endpoints e WHERE e.component_definition_id=d.id)
        ORDER BY d.id,r.interface_type""").fetchall()
    grouped = {}
    for definition_id, definition_key, interface_type in legacy:
        grouped.setdefault((definition_id, definition_key), []).append(interface_type)
    for (definition_id, definition_key), interfaces in grouped.items():
        structures = []
        for interface_type in interfaces:
            if interface_type in PROTOCOLS:
                structures.append({"kind": "protocol", "protocol": interface_type})
            elif definition_key == "aosong-dht22":
                structures.append({"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA"})
            elif definition_key == "generic-analog-soil-moisture-sensor":
                structures.append({"kind": "direct_signal", "signal_type": "analog_input", "endpoint_label": "SIGNAL"})
            elif definition_key == "generic-mosfet-switch-module":
                structures.append({"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "CONTROL"})
            elif interface_type == "analog_signal":
                structures.append({"kind": "direct_signal", "signal_type": "analog_input", "endpoint_label": "SIGNAL"})
            else:
                structures.append({"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "SIGNAL"})
        replace_interfaces(cur, definition_id, validate_interfaces(structures))
    _correct_legacy_dht22_endpoint(cur)


def _correct_legacy_dht22_endpoint(cur):
    """Correct only the narrow DHT22 shape produced by early v1.18 migrations."""
    rows = cur.execute("""SELECT endpoint.id
        FROM component_endpoints endpoint
        JOIN component_definitions definition
          ON definition.id=endpoint.component_definition_id
        WHERE endpoint.component_interface_id IS NULL
          AND endpoint.endpoint_key='signal' AND endpoint.endpoint_label='SIGNAL'
          AND endpoint.direct_signal_type='digital_io'
          AND (lower(coalesce(definition.model,'')) LIKE '%dht22%'
               OR lower(definition.display_name) LIKE '%dht22%'
               OR lower(coalesce(definition.model,'')) LIKE '%am2302%'
               OR lower(definition.display_name) LIKE '%am2302%')
          AND EXISTS (
              SELECT 1 FROM component_interface_requirements requirement
              WHERE requirement.component_definition_id=definition.id
                AND requirement.interface_type='digital_signal'
          )
          AND 1=(SELECT count(*) FROM component_endpoints sibling
                 WHERE sibling.component_definition_id=definition.id)
          AND 2=(SELECT count(*) FROM endpoint_required_capabilities requirement
                 WHERE requirement.endpoint_id=endpoint.id
                   AND requirement.capability IN ('digital_input','digital_output'))
          AND 2=(SELECT count(*) FROM endpoint_required_capabilities requirement
                 WHERE requirement.endpoint_id=endpoint.id)
          AND EXISTS (
              SELECT 1 FROM component_capabilities mapping
              JOIN capabilities capability ON capability.id=mapping.capability_id
              WHERE mapping.component_definition_id=definition.id
                AND capability.capability_key='temperature_measurement'
          )
          AND EXISTS (
              SELECT 1 FROM component_capabilities mapping
              JOIN capabilities capability ON capability.id=mapping.capability_id
              WHERE mapping.component_definition_id=definition.id
                AND capability.capability_key='humidity_measurement'
          )""").fetchall()
    cur.executemany(
        "UPDATE component_endpoints SET endpoint_key='data',endpoint_label='DATA' WHERE id=?",
        rows,
    )


def replace_interfaces(cur, definition_id, structures):
    cur.execute("DELETE FROM component_endpoints WHERE component_definition_id=?", (definition_id,))
    cur.execute("DELETE FROM component_interfaces WHERE component_definition_id=?", (definition_id,))
    for sequence, item in enumerate(structures):
        if item["kind"] == "protocol":
            cur.execute("INSERT INTO component_interfaces(component_definition_id,interface_key,interface_type,sequence) VALUES(?,?,?,?)",
                        (definition_id, item["interface_key"], item["protocol"], sequence))
            interface_id = cur.lastrowid
            canonical = {row[0]: row for row in PROTOCOLS[item["protocol"]]}
            for endpoint_sequence, key in enumerate(item["endpoints"]):
                _, label, capability = canonical[key]
                cur.execute("""INSERT INTO component_endpoints(component_definition_id,component_interface_id,
                    endpoint_key,endpoint_label,required,sequence) VALUES(?,?,?,?,1,?)""",
                            (definition_id, interface_id, key, label, endpoint_sequence))
                cur.execute("INSERT INTO endpoint_required_capabilities VALUES(?,?)", (cur.lastrowid, capability))
            for address in item["i2c_address_options"]:
                cur.execute("INSERT INTO component_i2c_address_options VALUES(?,?)", (interface_id, int(address, 16)))
        else:
            label, requirements = DIRECT_SIGNALS[item["signal_type"]]
            cur.execute("""INSERT INTO component_endpoints(component_definition_id,component_interface_id,
                endpoint_key,endpoint_label,required,direct_signal_type,sequence) VALUES(?,NULL,?,?,?,?,?)""",
                        (definition_id, item["endpoint_key"], item["endpoint_label"],
                         not item["optional"], item["signal_type"], sequence))
            endpoint_id = cur.lastrowid
            cur.executemany("INSERT INTO endpoint_required_capabilities VALUES(?,?)",
                            [(endpoint_id, capability) for capability in requirements])


def load_interfaces(conn, definition_ids):
    result = {definition_id: [] for definition_id in definition_ids}
    if not definition_ids:
        return result
    marks = ",".join("?" for _ in definition_ids)
    interfaces = conn.execute(f"SELECT * FROM component_interfaces WHERE component_definition_id IN ({marks}) ORDER BY component_definition_id,sequence", definition_ids).fetchall()
    endpoints = conn.execute(f"""SELECT e.*,group_concat(c.capability) requirements FROM component_endpoints e
        LEFT JOIN endpoint_required_capabilities c ON c.endpoint_id=e.id
        WHERE e.component_definition_id IN ({marks}) GROUP BY e.id ORDER BY e.component_definition_id,e.sequence""", definition_ids).fetchall()
    endpoint_by_interface = {}
    for row in endpoints:
        endpoint = {"endpoint_key": row["endpoint_key"], "endpoint_label": row["endpoint_label"],
                    "required": bool(row["required"]), "required_capabilities": sorted((row["requirements"] or "").split(","))}
        if row["component_interface_id"] is None:
            result[row["component_definition_id"]].append({"kind": "direct_signal", **endpoint,
                "signal_type": row["direct_signal_type"],
                "signal_type_label": DIRECT_SIGNALS[row["direct_signal_type"]][0],
                "_sequence": row["sequence"]})
        else:
            endpoint_by_interface.setdefault(row["component_interface_id"], []).append(endpoint)
    for row in interfaces:
        addresses = [f"0x{item[0]:02X}" for item in conn.execute(
            "SELECT address FROM component_i2c_address_options WHERE component_interface_id=? ORDER BY address", (row["id"],))]
        result[row["component_definition_id"]].append({"kind": "protocol", "interface_key": row["interface_key"],
            "interface_label": row["interface_key"].upper().replace("I2C", "I²C"), "protocol": row["interface_type"],
            "endpoints": endpoint_by_interface.get(row["id"], []),
            "i2c_address_options": addresses, "_sequence": row["sequence"]})
    for items in result.values():
        items.sort(key=lambda item: item["_sequence"])
        for item in items:
            item.pop("_sequence")
    return result


def deactivate_mappings(cur, connected_db_id):
    timestamp = database.now_string()
    cur.execute("UPDATE connected_component_hardware_mappings SET active=0,removed_at=? WHERE connected_component_id=? AND active=1", (timestamp, connected_db_id))
    cur.execute("UPDATE connected_component_interface_configuration SET active=0,removed_at=? WHERE connected_component_id=? AND active=1", (timestamp, connected_db_id))


def _context(conn, node_id, public_id):
    conn.row_factory = sqlite3.Row
    return conn.execute("""SELECT c.id connected_id,c.connected_component_id,c.component_definition_id,
        c.lifecycle_status,n.id node_db_id,n.hardware_platform_id,p.id platform_id
        FROM connected_components c JOIN nodes n ON n.id=c.node_db_id
        LEFT JOIN hardware_platforms p ON p.hardware_platform_id=n.hardware_platform_id
        WHERE n.node_id=? AND c.connected_component_id=?""", (node_id, public_id)).fetchone()


def _mapping_rows(conn, connected_id):
    return conn.execute("""SELECT m.endpoint_id,m.hardware_resource_id,r.resource_name
        FROM connected_component_hardware_mappings m JOIN hardware_platform_resources r ON r.id=m.hardware_resource_id
        WHERE m.connected_component_id=? AND m.active=1""", (connected_id,)).fetchall()


def _endpoint_requirements(conn, endpoint_ids):
    """Load complete endpoint roles in one query; multi-capability roles stay intact."""
    result = {endpoint_id: frozenset() for endpoint_id in endpoint_ids}
    if not endpoint_ids:
        return result
    placeholders = ",".join("?" for _ in endpoint_ids)
    for endpoint_id, capability in conn.execute(f"""SELECT endpoint_id,capability
        FROM endpoint_required_capabilities WHERE endpoint_id IN ({placeholders})""",
        list(endpoint_ids)):
        result[endpoint_id] = result[endpoint_id] | {capability}
    return result


def can_share(existing_requirements, proposed_requirements):
    """Only identical, explicitly shareable protocol roles may share a resource."""
    existing = frozenset(existing_requirements)
    proposed = frozenset(proposed_requirements)
    return existing == proposed and proposed in SHAREABLE_ROLES


def _role_label(endpoint, requirements):
    if endpoint["component_interface_id"] is not None:
        return PROTOCOL_ROLE_LABELS.get(frozenset(requirements), "Invalid mapping")
    signal = DIRECT_SIGNALS.get(endpoint["direct_signal_type"])
    return signal[0] if signal else "Invalid mapping"


def _active_allocations(conn, node_db_id, excluded_connected_id=None):
    params = [node_db_id]
    excluded = ""
    if excluded_connected_id is not None:
        excluded = "AND connected.id<>?"
        params.append(excluded_connected_id)
    rows = conn.execute(f"""SELECT mapping.hardware_resource_id,mapping.endpoint_id,
            endpoint.component_interface_id,endpoint.direct_signal_type
        FROM connected_component_hardware_mappings mapping
        JOIN connected_components connected ON connected.id=mapping.connected_component_id
        JOIN component_endpoints endpoint ON endpoint.id=mapping.endpoint_id
        WHERE mapping.active=1 AND connected.lifecycle_status='active'
          AND connected.node_db_id=? {excluded}""", params).fetchall()
    requirements = _endpoint_requirements(conn, {row["endpoint_id"] for row in rows})
    by_resource = {}
    for row in rows:
        by_resource.setdefault(row["hardware_resource_id"], []).append({
            "endpoint_id": row["endpoint_id"],
            "requirements": requirements[row["endpoint_id"]],
            "role": _role_label(row, requirements[row["endpoint_id"]]),
        })
    return by_resource


def _i2c_pairs(conn, node_db_id, excluded_connected_id=None):
    params = [node_db_id]
    excluded = ""
    if excluded_connected_id is not None:
        excluded = "AND connected.id<>?"
        params.append(excluded_connected_id)
    return conn.execute(f"""SELECT connected.id connected_id,interface.id interface_id,
            sda_mapping.hardware_resource_id sda_resource_id,
            scl_mapping.hardware_resource_id scl_resource_id,configuration.i2c_address
        FROM connected_components connected
        JOIN component_interfaces interface
          ON interface.component_definition_id=connected.component_definition_id
         AND interface.interface_type='i2c'
        JOIN component_endpoints sda
          ON sda.component_interface_id=interface.id AND sda.endpoint_key='sda'
        JOIN component_endpoints scl
          ON scl.component_interface_id=interface.id AND scl.endpoint_key='scl'
        JOIN connected_component_hardware_mappings sda_mapping
          ON sda_mapping.connected_component_id=connected.id
         AND sda_mapping.endpoint_id=sda.id AND sda_mapping.active=1
        JOIN connected_component_hardware_mappings scl_mapping
          ON scl_mapping.connected_component_id=connected.id
         AND scl_mapping.endpoint_id=scl.id AND scl_mapping.active=1
        JOIN connected_component_interface_configuration configuration
          ON configuration.connected_component_id=connected.id
         AND configuration.component_interface_id=interface.id AND configuration.active=1
        WHERE connected.node_db_id=? AND connected.lifecycle_status='active' {excluded}""",
        params).fetchall()


def _persisted_mapping_invalid(conn, connected_id, definition_id):
    """Diagnose active persisted mapping state without mutating configuration."""
    context = conn.execute("""SELECT connected.node_db_id,platform.id platform_id
        FROM connected_components connected
        JOIN nodes node ON node.id=connected.node_db_id
        LEFT JOIN hardware_platforms platform
          ON platform.hardware_platform_id=node.hardware_platform_id
        WHERE connected.id=? AND connected.component_definition_id=?""",
        (connected_id, definition_id)).fetchone()
    if context is None:
        return True

    mappings = conn.execute("""SELECT mapping.id,mapping.endpoint_id,
            mapping.hardware_resource_id,endpoint.component_definition_id,
            endpoint.component_interface_id,endpoint.endpoint_key,
            endpoint.direct_signal_type,interface.component_definition_id interface_definition_id,
            interface.interface_type,resource.hardware_platform_db_id
        FROM connected_component_hardware_mappings mapping
        LEFT JOIN component_endpoints endpoint ON endpoint.id=mapping.endpoint_id
        LEFT JOIN component_interfaces interface
          ON interface.id=endpoint.component_interface_id
        LEFT JOIN hardware_platform_resources resource
          ON resource.id=mapping.hardware_resource_id
        WHERE mapping.connected_component_id=? AND mapping.active=1""",
        (connected_id,)).fetchall()
    configurations = conn.execute("""SELECT configuration.component_interface_id,
            configuration.i2c_address,interface.component_definition_id,
            interface.interface_type
        FROM connected_component_interface_configuration configuration
        LEFT JOIN component_interfaces interface
          ON interface.id=configuration.component_interface_id
        WHERE configuration.connected_component_id=? AND configuration.active=1""",
        (connected_id,)).fetchall()
    if not mappings and not configurations:
        return False
    if context["platform_id"] is None:
        return True
    for row in mappings:
        if (row["component_definition_id"] != definition_id
                or row["hardware_platform_db_id"] != context["platform_id"]):
            return True
        if row["component_interface_id"] is None:
            if row["direct_signal_type"] not in DIRECT_SIGNALS:
                return True
        else:
            protocol_endpoints = PROTOCOLS.get(row["interface_type"], ())
            if (row["interface_definition_id"] != definition_id
                    or row["endpoint_key"] not in {
                        endpoint[0] for endpoint in protocol_endpoints
                    }):
                return True
    if any(row["component_definition_id"] != definition_id
           or row["interface_type"] != "i2c" for row in configurations):
        return True

    endpoint_ids = {row["endpoint_id"] for row in mappings}
    requirements = _endpoint_requirements(conn, endpoint_ids)
    resource_ids = {row["hardware_resource_id"] for row in mappings}
    supported = {resource_id: set() for resource_id in resource_ids}
    if resource_ids:
        placeholders = ",".join("?" for _ in resource_ids)
        for resource_id, capability in conn.execute(f"""SELECT hardware_resource_id,
                capability FROM hardware_resource_capabilities
            WHERE hardware_resource_id IN ({placeholders})""", list(resource_ids)):
            supported[resource_id].add(capability)
    if any(not requirements[row["endpoint_id"]] <= supported[row["hardware_resource_id"]]
           for row in mappings):
        return True

    node_allocations = conn.execute("""SELECT mapping.id,mapping.hardware_resource_id,
            mapping.endpoint_id
        FROM connected_component_hardware_mappings mapping
        JOIN connected_components connected ON connected.id=mapping.connected_component_id
        WHERE connected.node_db_id=? AND connected.lifecycle_status='active'
          AND mapping.active=1""", (context["node_db_id"],)).fetchall()
    allocation_requirements = _endpoint_requirements(
        conn, {row["endpoint_id"] for row in node_allocations}
    )
    by_resource = {}
    for row in node_allocations:
        by_resource.setdefault(row["hardware_resource_id"], []).append(row)
    for mapping in mappings:
        for other in by_resource.get(mapping["hardware_resource_id"], []):
            if other["id"] == mapping["id"]:
                continue
            if not can_share(requirements[mapping["endpoint_id"]],
                             allocation_requirements[other["endpoint_id"]]):
                return True

    interfaces = conn.execute("""SELECT id,interface_type FROM component_interfaces
        WHERE component_definition_id=?""", (definition_id,)).fetchall()
    i2c_interface_ids = {
        row["id"] for row in interfaces if row["interface_type"] == "i2c"
    }
    endpoints_by_interface = {interface_id: {} for interface_id in i2c_interface_ids}
    options_by_interface = {interface_id: set() for interface_id in i2c_interface_ids}
    if i2c_interface_ids:
        placeholders = ",".join("?" for _ in i2c_interface_ids)
        for endpoint_id, interface_id, endpoint_key in conn.execute(f"""SELECT id,
                component_interface_id,endpoint_key FROM component_endpoints
            WHERE component_interface_id IN ({placeholders})
              AND endpoint_key IN ('sda','scl')""", list(i2c_interface_ids)):
            endpoints_by_interface[interface_id][endpoint_key] = endpoint_id
        for interface_id, address in conn.execute(f"""SELECT component_interface_id,
                address FROM component_i2c_address_options
            WHERE component_interface_id IN ({placeholders})""", list(i2c_interface_ids)):
            options_by_interface[interface_id].add(address)
    configuration_by_interface = {}
    for row in configurations:
        if row["component_interface_id"] in configuration_by_interface:
            return True
        configuration_by_interface[row["component_interface_id"]] = row["i2c_address"]
    mapped_by_endpoint = {row["endpoint_id"]: row["hardware_resource_id"] for row in mappings}
    current_pairs = []
    for interface in interfaces:
        if interface["interface_type"] != "i2c":
            continue
        endpoint_by_key = endpoints_by_interface[interface["id"]]
        if set(endpoint_by_key) != {"sda", "scl"}:
            return True
        pair = {key: mapped_by_endpoint.get(endpoint_by_key[key])
                for key in ("sda", "scl")}
        mapped_count = sum(value is not None for value in pair.values())
        address = configuration_by_interface.pop(interface["id"], None)
        if mapped_count == 1 or (mapped_count == 0 and address is not None):
            return True
        if mapped_count == 0:
            continue
        if address is None or not 0x08 <= address <= 0x77:
            return True
        options = options_by_interface[interface["id"]]
        if options and address not in options:
            return True
        current_pairs.append({
            "sda_resource_id": pair["sda"], "scl_resource_id": pair["scl"],
            "i2c_address": address,
        })
    if configuration_by_interface:
        return True

    other_pairs = _i2c_pairs(conn, context["node_db_id"], connected_id)
    for pair in current_pairs:
        for other in other_pairs:
            same_sda = pair["sda_resource_id"] == other["sda_resource_id"]
            same_scl = pair["scl_resource_id"] == other["scl_resource_id"]
            if same_sda != same_scl:
                return True
            if (same_sda and same_scl
                    and pair["i2c_address"] == other["i2c_address"]):
                return True
    return False


def mapping_state(conn, connected_id, definition_id, active=True):
    endpoints = conn.execute("SELECT id,required FROM component_endpoints WHERE component_definition_id=?", (definition_id,)).fetchall()
    mapped = {row[0] for row in _mapping_rows(conn, connected_id)} if active else set()
    if active and _persisted_mapping_invalid(conn, connected_id, definition_id):
        return "Invalid"
    if not endpoints:
        return "Mapped"
    if not mapped:
        return "Unmapped"
    required = {row[0] for row in endpoints if row[1]}
    if required <= mapped:
        return "Mapped"
    return "Partially Mapped"


def get_mapping(node_id, public_id):
    conn = database.get_connection(); conn.row_factory = sqlite3.Row
    try:
        context = _context(conn, node_id, public_id)
        if context is None:
            return None
        structures = load_interfaces(conn, [context["component_definition_id"]])[context["component_definition_id"]]
        mapped = {row["endpoint_id"]: row for row in _mapping_rows(conn, context["connected_id"])}
        endpoint_ids = {(row["component_interface_id"], row["endpoint_key"]): row["id"] for row in conn.execute(
            "SELECT id,component_interface_id,endpoint_key FROM component_endpoints WHERE component_definition_id=?", (context["component_definition_id"],))}
        interface_ids = {row["interface_key"]: row["id"] for row in conn.execute(
            "SELECT id,interface_key FROM component_interfaces WHERE component_definition_id=?", (context["component_definition_id"],))}
        addresses = {row["component_interface_id"]: f"0x{row['i2c_address']:02X}" for row in conn.execute(
            "SELECT component_interface_id,i2c_address FROM connected_component_interface_configuration WHERE connected_component_id=? AND active=1", (context["connected_id"],))}
        resources = []
        active_allocations = _active_allocations(
            conn, context["node_db_id"], context["connected_id"]
        )
        if context["platform_id"]:
            for resource in conn.execute("""SELECT r.id,r.resource_name,group_concat(c.capability) capabilities
                FROM hardware_platform_resources r LEFT JOIN hardware_resource_capabilities c ON c.hardware_resource_id=r.id
                WHERE r.hardware_platform_db_id=? GROUP BY r.id ORDER BY r.resource_name COLLATE NOCASE""", (context["platform_id"],)):
                resources.append({"resource_id": resource["id"], "resource": resource["resource_name"],
                                  "capabilities": sorted((resource["capabilities"] or "").split(","))})
        for item in structures:
            iid = interface_ids.get(item.get("interface_key"))
            item["selected_i2c_address"] = addresses.get(iid)
            for endpoint in item.get("endpoints", [item]):
                eid = endpoint_ids[(iid, endpoint["endpoint_key"])]
                endpoint["endpoint_id"] = eid
                endpoint["mapped_resource"] = ({"resource_id": mapped[eid]["hardware_resource_id"], "resource": mapped[eid]["resource_name"]} if eid in mapped else None)
                required = frozenset(endpoint["required_capabilities"])
                eligible = []
                for resource in resources:
                    allocations = active_allocations.get(resource["resource_id"], [])
                    compatible_occupancy = all(
                        can_share(allocation["requirements"], required)
                        for allocation in allocations
                    )
                    if required <= set(resource["capabilities"]) and compatible_occupancy:
                        candidate = resource.copy()
                        candidate["occupancy_state"] = (
                            "Shared" if allocations else "Free"
                        )
                        candidate["occupancy_roles"] = sorted({
                            allocation["role"] for allocation in allocations
                        })
                        eligible.append(candidate)
                endpoint["eligible_resources"] = eligible
        return {"hardware_platform_id": context["hardware_platform_id"], "interfaces_signals": structures,
                "mapping_state": mapping_state(conn, context["connected_id"], context["component_definition_id"], context["lifecycle_status"] == "active")}
    finally:
        conn.close()


def save_mapping(node_id, public_id, payload):
    if (not isinstance(payload, dict)
            or set(payload) != {"mappings", "i2c_addresses"}
            or not isinstance(payload["mappings"], list)
            or not isinstance(payload["i2c_addresses"], dict)):
        raise MappingValidationError([{
            "code": "invalid_payload",
            "message": "A complete mappings and i2c_addresses payload is required",
        }])
    conn = database.get_connection()
    conn.row_factory = sqlite3.Row
    try:
        context = _context(conn, node_id, public_id)
        if context is None:
            raise LookupError("Connected component not found")
        errors = []
        if context["lifecycle_status"] != "active":
            errors.append({
                "code": "removed_component",
                "message": "Removed components cannot be mapped",
            })
        if not context["platform_id"]:
            errors.append({
                "code": "hardware_platform_required",
                "message": "The Node must have an assigned Hardware Platform",
            })
        endpoint_rows = conn.execute("""SELECT endpoint.*,interface.interface_key,
                interface.interface_type
            FROM component_endpoints endpoint
            LEFT JOIN component_interfaces interface
              ON interface.id=endpoint.component_interface_id
            WHERE endpoint.component_definition_id=?""",
            (context["component_definition_id"],)).fetchall()
        endpoints = {row["id"]: row for row in endpoint_rows}
        requirements = _endpoint_requirements(conn, endpoints)
        proposed = {}
        for item in payload["mappings"]:
            if (not isinstance(item, dict)
                    or set(item) != {"endpoint_id", "resource_id"}
                    or item["endpoint_id"] in proposed):
                errors.append({
                    "code": "invalid_mapping",
                    "message": "Each endpoint mapping must be unique",
                })
                continue
            endpoint = endpoints.get(item["endpoint_id"])
            resource = conn.execute("""SELECT id,hardware_platform_db_id
                FROM hardware_platform_resources WHERE id=?""",
                (item["resource_id"],)).fetchone()
            if endpoint is None:
                errors.append({
                    "code": "wrong_endpoint",
                    "message": "Mapping endpoint does not belong to this Component Definition",
                })
                continue
            if resource is None or resource["hardware_platform_db_id"] != context["platform_id"]:
                errors.append({
                    "code": "wrong_resource",
                    "endpoint_id": item["endpoint_id"],
                    "message": "Resource does not belong to the Node's Hardware Platform",
                })
                continue
            supported = {row[0] for row in conn.execute("""SELECT capability
                FROM hardware_resource_capabilities WHERE hardware_resource_id=?""",
                (resource["id"],))}
            if not requirements[endpoint["id"]] <= supported:
                errors.append({
                    "code": "incompatible_resource",
                    "endpoint_id": endpoint["id"],
                    "message": "Resource does not satisfy all endpoint capabilities",
                })
                continue
            proposed[endpoint["id"]] = resource["id"]

        existing_allocations = _active_allocations(
            conn, context["node_db_id"], context["connected_id"]
        )
        for eid, rid in proposed.items():
            for allocation in existing_allocations.get(rid, []):
                if not can_share(allocation["requirements"], requirements[eid]):
                    errors.append({
                        "code": "resource_role_conflict",
                        "endpoint_id": eid,
                        "message": "Resource is allocated to an incompatible or exclusive role",
                    })
        by_resource = {}
        for eid, rid in proposed.items():
            by_resource.setdefault(rid, []).append(eid)
        for endpoint_ids in by_resource.values():
            for index, endpoint_id in enumerate(endpoint_ids):
                for other_id in endpoint_ids[index + 1:]:
                    if not can_share(requirements[endpoint_id], requirements[other_id]):
                        errors.append({
                            "code": "resource_role_conflict",
                            "message": "One resource cannot satisfy incompatible or exclusive endpoint roles",
                        })

        interfaces = conn.execute("""SELECT * FROM component_interfaces
            WHERE component_definition_id=?""",
            (context["component_definition_id"],)).fetchall()
        interface_by_key = {row["interface_key"]: row for row in interfaces}
        i2c_endpoint_ids = {}
        for endpoint in endpoints.values():
            if endpoint["interface_type"] == "i2c":
                i2c_endpoint_ids.setdefault(endpoint["component_interface_id"], {})[
                    endpoint["endpoint_key"]
                ] = endpoint["id"]

        parsed_addresses = {}
        for key, value in payload["i2c_addresses"].items():
            interface = interface_by_key.get(key)
            if interface is None or interface["interface_type"] != "i2c":
                errors.append({
                    "code": "wrong_interface",
                    "message": "I²C address references an invalid interface",
                })
                continue
            try:
                address = int(normalize_address(value), 16)
            except ValueError as error:
                errors.append({"code": "invalid_i2c_address", "message": str(error)})
                continue
            options = {row[0] for row in conn.execute("""SELECT address
                FROM component_i2c_address_options WHERE component_interface_id=?""",
                (interface["id"],))}
            if options and address not in options:
                errors.append({
                    "code": "i2c_address_not_allowed",
                    "message": "Selected I²C address is not an allowed definition option",
                })
                continue
            parsed_addresses[interface["id"]] = address

        existing_pairs = _i2c_pairs(
            conn, context["node_db_id"], context["connected_id"]
        )
        proposed_pairs = []
        for interface in interfaces:
            if interface["interface_type"] != "i2c":
                continue
            endpoint_ids = i2c_endpoint_ids[interface["id"]]
            pair = {
                key: proposed.get(endpoint_ids[key]) for key in ("sda", "scl")
            }
            mapped_count = sum(resource_id is not None for resource_id in pair.values())
            if mapped_count == 1:
                errors.append({
                    "code": "incomplete_i2c_interface",
                    "message": f"{interface['interface_key']} must map both SDA and SCL or neither",
                })
                continue
            address = parsed_addresses.get(interface["id"])
            if mapped_count == 0:
                if address is not None:
                    errors.append({
                        "code": "i2c_address_without_mapping",
                        "message": f"{interface['interface_key']} cannot store an address while unmapped",
                    })
                continue
            if address is None:
                errors.append({
                    "code": "i2c_address_required",
                    "message": f"{interface['interface_key']} requires an address when mapped",
                })
                continue
            for existing in [*existing_pairs, *proposed_pairs]:
                same_sda = pair["sda"] == existing["sda_resource_id"]
                same_scl = pair["scl"] == existing["scl_resource_id"]
                if same_sda != same_scl:
                    errors.append({
                        "code": "i2c_topology_conflict",
                        "message": "Shared I²C lines must use the same complete SDA/SCL pair",
                    })
                elif same_sda and existing["i2c_address"] == address:
                    errors.append({
                        "code": "i2c_address_collision",
                        "message": "I²C address is already used on the inferred SDA/SCL bus",
                    })
            proposed_pairs.append({
                "sda_resource_id": pair["sda"],
                "scl_resource_id": pair["scl"],
                "i2c_address": address,
            })

        if errors:
            raise MappingValidationError(errors)
        deactivate_mappings(conn.cursor(), context["connected_id"])
        timestamp = database.now_string()
        conn.executemany("""INSERT INTO connected_component_hardware_mappings
            (connected_component_id,endpoint_id,hardware_resource_id,created_at)
            VALUES(?,?,?,?)""", [
                (context["connected_id"], endpoint_id, resource_id, timestamp)
                for endpoint_id, resource_id in proposed.items()
            ])
        mapped_i2c_interfaces = {
            endpoint["component_interface_id"] for endpoint_id, endpoint in endpoints.items()
            if endpoint_id in proposed and endpoint["interface_type"] == "i2c"
        }
        conn.executemany("""INSERT INTO connected_component_interface_configuration
            (connected_component_id,component_interface_id,i2c_address,created_at)
            VALUES(?,?,?,?)""", [
                (context["connected_id"], interface_id,
                 parsed_addresses[interface_id], timestamp)
                for interface_id in mapped_i2c_interfaces
            ])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_mapping(node_id, public_id)


def _allocation_display(row):
    """Return neutral allocation text when persisted endpoint metadata is corrupt."""
    endpoint_label = row["endpoint_label"]
    interface_type = row["interface_type"]
    if not endpoint_label:
        return "Invalid mapping", "—"
    if interface_type:
        endpoints = PROTOCOLS.get(interface_type, ())
        capability = next(
            (item[2] for item in endpoints if item[0] == row["endpoint_key"]), None
        )
        if capability is None or not row["interface_key"]:
            return "Invalid mapping", "—"
        return (
            CAPABILITY_LABELS[capability],
            f"{row['interface_key'].upper().replace('I2C', 'I²C')} / {endpoint_label}",
        )
    signal = DIRECT_SIGNALS.get(row["direct_signal_type"])
    if signal is None:
        return "Invalid mapping", "—"
    return signal[0], endpoint_label


def node_allocation(node_id):
    conn = database.get_connection()
    conn.row_factory = sqlite3.Row
    try:
        node = conn.execute("SELECT id,hardware_platform_id FROM nodes WHERE node_id=?", (node_id,)).fetchone()
        if node is None:
            return None
        if not node["hardware_platform_id"]:
            return {
                "mapping_state": "Incomplete", "used": 0, "shared": 0,
                "free": 0, "resources": [],
            }
        rows = conn.execute("""SELECT resource.id,resource.resource_name,
            mapping.id mapping_id,endpoint.endpoint_label,endpoint.endpoint_key,
            endpoint.direct_signal_type,interface.interface_key,interface.interface_type,
            connected.connected_component_id,connected.label,
            connected.component_definition_id
            FROM hardware_platforms p
            JOIN hardware_platform_resources resource
              ON resource.hardware_platform_db_id=p.id
            LEFT JOIN connected_component_hardware_mappings mapping
              ON mapping.hardware_resource_id=resource.id AND mapping.active=1
             AND mapping.connected_component_id IN (
                SELECT id FROM connected_components
                WHERE node_db_id=? AND lifecycle_status='active'
             )
            LEFT JOIN connected_components connected
              ON connected.id=mapping.connected_component_id
            LEFT JOIN component_endpoints endpoint ON endpoint.id=mapping.endpoint_id
            LEFT JOIN component_interfaces interface
              ON interface.id=endpoint.component_interface_id
            WHERE p.hardware_platform_id=?
            ORDER BY resource.resource_name COLLATE NOCASE,connected.label""",
            (node["id"], node["hardware_platform_id"])).fetchall()
        resources = {}
        for row in rows:
            item = resources.setdefault(row["id"], {
                "resource_id": row["id"], "resource": row["resource_name"],
                "allocations": [],
            })
            if row["mapping_id"] and row["connected_component_id"]:
                role, interface_signal = _allocation_display(row)
                item["allocations"].append({
                    "role": role,
                    "interface_signal": interface_signal,
                    "connected_component_id": row["connected_component_id"],
                    "connected_component": row["label"],
                })
        for item in resources.values():
            item["state"] = (
                "Free" if not item["allocations"]
                else "Shared" if len(item["allocations"]) > 1
                else "Allocated"
            )
        used = sum(item["state"] != "Free" for item in resources.values())
        shared = sum(item["state"] == "Shared" for item in resources.values())
        components = conn.execute("""SELECT id,component_definition_id
            FROM connected_components
            WHERE node_db_id=? AND lifecycle_status='active'""",
            (node["id"],)).fetchall()
        states = [mapping_state(conn, row["id"], row["component_definition_id"]) for row in components]
        node_state = (
            "Invalid" if "Invalid" in states
            else "Complete" if states and all(state == "Mapped" for state in states)
            else "Incomplete"
        )
        from app.hardware_platforms import natural_resource_key
        ordered_resources = sorted(
            resources.values(), key=lambda item: natural_resource_key(item["resource"])
        )
        return {"mapping_state": node_state,
                "used": used, "shared": shared, "free": len(resources)-used,
                "resources": ordered_resources}
    finally:
        conn.close()
