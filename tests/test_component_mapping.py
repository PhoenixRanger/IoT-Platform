import sqlite3

from app import database


def definition(structures):
    return {"display_name": "Mapped Peripheral", "manufacturer": None, "model": None,
            "component_class": "sensor", "interfaces_signals": structures,
            "capabilities": ["temperature_measurement"]}


def platform(client, resources):
    return client.post("/api/hardware-platforms", json={
        "display_name": "Mapping Board", "manufacturer": "Test", "model": "B1",
        "mcu": "MCU", "revision": None, "description": None, "resources": resources,
    }).get_json()


def node_and_component(client, definition_payload, resources):
    created = client.post("/api/components", json=definition_payload)
    assert created.status_code == 201, created.get_json()
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    board = platform(client, resources)
    assert client.put("/api/nodes/mapping-node/hardware-platform", json={
        "hardware_platform_id": board["hardware_platform_id"]}).status_code == 200
    component = client.post("/api/nodes/mapping-node/components", json={
        "definition_key": created.get_json()["definition_key"], "label": "Outside THP"}).get_json()
    mapping = client.get(f"/api/nodes/mapping-node/components/{component['connected_component_id']}/hardware-mapping").get_json()
    return created.get_json(), component, mapping


def test_protocol_keys_defaults_addresses_and_technical_lock(client):
    payload = definition([
        {"kind": "protocol", "protocol": "i2c", "i2c_address_options": ["0x76", "0x77"]},
        {"kind": "protocol", "protocol": "i2c"},
        {"kind": "protocol", "protocol": "uart"},
        {"kind": "protocol", "protocol": "spi"},
    ])
    created = client.post("/api/components", json=payload)
    assert created.status_code == 201
    structures = created.get_json()["interfaces_signals"]
    assert [item["interface_key"] for item in structures] == ["i2c-1", "i2c-2", "uart-1", "spi-1"]
    assert [x["endpoint_key"] for x in structures[2]["endpoints"]] == ["tx", "rx"]
    assert [x["endpoint_key"] for x in structures[3]["endpoints"]] == ["mosi", "miso", "sck", "cs"]
    assert structures[0]["i2c_address_options"] == ["0x76", "0x77"]
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    item = client.post("/api/nodes/mapping-node/components", json={
        "definition_key": created.get_json()["definition_key"], "label": "Physical"})
    assert item.status_code == 201
    locked = client.patch(f"/api/components/{created.get_json()['definition_key']}", json={"interfaces_signals": payload["interfaces_signals"]})
    assert locked.status_code == 400 and "permanently locked" in locked.get_json()["error"]


def test_i2c_requires_both_endpoints_and_address_validation(client):
    bad = definition([{"kind": "protocol", "protocol": "i2c", "endpoints": ["sda"]}])
    assert client.post("/api/components", json=bad).status_code == 400
    for address in ("76", "0x80", "nope"):
        payload = definition([{"kind": "protocol", "protocol": "i2c", "i2c_address_options": [address]}])
        assert client.post("/api/components", json=payload).status_code == 400


def test_i2c_definition_options_reject_reserved_address_ranges(client):
    valid = client.post("/api/components", json=definition([{
        "kind": "protocol", "protocol": "i2c",
        "i2c_address_options": ["0x8", "0x40", "0x77"],
    }]))
    assert valid.status_code == 201
    assert valid.get_json()["interfaces_signals"][0]["i2c_address_options"] == [
        "0x08", "0x40", "0x77",
    ]

    for address in ("0x00", "0x01", "0x07", "0x78", "0x7F", "0x80"):
        response = client.post("/api/components", json=definition([{
            "kind": "protocol", "protocol": "i2c",
            "i2c_address_options": [address],
        }]))
        assert response.status_code == 400
        assert response.get_json()["error"] == (
            "I²C peripheral address must be in the usable 7-bit range 0x08–0x77"
        )


def test_manual_i2c_addresses_reject_reserved_ranges_atomically(
        client, isolated_database):
    _, component, mapping = node_and_component(client, definition([{
        "kind": "protocol", "protocol": "i2c",
    }]), [
        {"resource": "SDA", "capabilities": ["i2c_sda"]},
        {"resource": "SCL", "capabilities": ["i2c_scl"]},
    ])
    resources = resource_ids(isolated_database)
    mappings = [
        {"endpoint_id": endpoint_id(mapping, "sda", "i2c-1"),
         "resource_id": resources["SDA"]},
        {"endpoint_id": endpoint_id(mapping, "scl", "i2c-1"),
         "resource_id": resources["SCL"]},
    ]

    for address in ("0x08", "0x40", "0x77"):
        response = put_mapping(client, component, mappings, {"i2c-1": address})
        assert response.status_code == 200
        assert response.get_json()["interfaces_signals"][0][
            "selected_i2c_address"
        ] == address

    for address in ("0x00", "0x07", "0x78", "0x7F", "0x80"):
        response = put_mapping(client, component, mappings, {"i2c-1": address})
        assert response.status_code == 400
        invalid_address = next(
            error for error in response.get_json()["validation_errors"]
            if error["code"] == "invalid_i2c_address"
        )
        assert invalid_address["message"] == (
            "I²C peripheral address must be in the usable 7-bit range 0x08–0x77"
        )
        persisted = client.get(mapping_url(component)).get_json()
        assert persisted["mapping_state"] == "Mapped"
        assert persisted["interfaces_signals"][0]["selected_i2c_address"] == "0x77"
        assert {
            endpoint["mapped_resource"]["resource"]
            for endpoint in persisted["interfaces_signals"][0]["endpoints"]
        } == {"SDA", "SCL"}


def test_digital_io_requires_both_capabilities_and_optional_semantics(client):
    created = client.post("/api/components", json=definition([
        {"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA"},
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "ALERT", "optional": True},
    ])).get_json()
    data, alert = created["interfaces_signals"]
    assert data["endpoint_key"] == "data"
    assert data["required_capabilities"] == ["digital_input", "digital_output"]
    assert alert["required"] is False


def test_atomic_direct_mapping_compatibility_and_allocation(client, isolated_database):
    _, component, mapping = node_and_component(client, definition([
        {"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA"},
    ]), [{"resource": "IO_17", "capabilities": ["digital_input", "digital_output"]},
         {"resource": "A0", "capabilities": ["adc"]}])
    endpoint = mapping["interfaces_signals"][0]
    assert [x["resource"] for x in endpoint["eligible_resources"]] == ["IO_17"]
    url = f"/api/nodes/mapping-node/components/{component['connected_component_id']}/hardware-mapping"
    bad = client.put(url, json={"mappings": [{"endpoint_id": endpoint["endpoint_id"], "resource_id": 999999}], "i2c_addresses": {}})
    assert bad.status_code == 400 and bad.get_json()["validation_errors"][0]["code"] == "wrong_resource"
    with sqlite3.connect(isolated_database) as conn:
        assert conn.execute("SELECT COUNT(*) FROM connected_component_hardware_mappings WHERE active=1").fetchone()[0] == 0
    resource = endpoint["eligible_resources"][0]
    assert client.put(url, json={"mappings": [{"endpoint_id": endpoint["endpoint_id"], "resource_id": resource["resource_id"]}], "i2c_addresses": {}}).get_json()["mapping_state"] == "Mapped"
    allocation = client.get("/api/nodes/mapping-node/hardware-allocation").get_json()
    assert (allocation["used"], allocation["shared"], allocation["free"]) == (1, 0, 1)
    assert {x["resource"]: x["state"] for x in allocation["resources"]} == {"A0": "Free", "IO_17": "Allocated"}


def test_i2c_bus_sharing_distinct_addresses_and_collision(client):
    definition_payload = definition([{"kind": "protocol", "protocol": "i2c", "i2c_address_options": ["0x40", "0x41"]}])
    created, first, mapping = node_and_component(client, definition_payload, [
        {"resource": "SENSOR_SDA", "capabilities": ["i2c_sda"]},
        {"resource": "SENSOR_SCL", "capabilities": ["i2c_scl"]},
    ])
    second = client.post("/api/nodes/mapping-node/components", json={"definition_key": created["definition_key"], "label": "Inside THP"}).get_json()
    def payload_for(component, address):
        data = client.get(f"/api/nodes/mapping-node/components/{component['connected_component_id']}/hardware-mapping").get_json()
        interface = data["interfaces_signals"][0]
        mappings = [{"endpoint_id": endpoint["endpoint_id"], "resource_id": endpoint["eligible_resources"][0]["resource_id"]} for endpoint in interface["endpoints"]]
        return {"mappings": mappings, "i2c_addresses": {"i2c-1": address}}
    base = "/api/nodes/mapping-node/components/"
    assert client.put(base + first["connected_component_id"] + "/hardware-mapping", json=payload_for(first, "0x40")).status_code == 200
    collision = client.put(base + second["connected_component_id"] + "/hardware-mapping", json=payload_for(second, "0x40"))
    assert collision.status_code == 400 and any(x["code"] == "i2c_address_collision" for x in collision.get_json()["validation_errors"])
    assert client.put(base + second["connected_component_id"] + "/hardware-mapping", json=payload_for(second, "0x41")).status_code == 200
    allocation = client.get("/api/nodes/mapping-node/hardware-allocation").get_json()
    assert allocation["used"] == 2 and allocation["shared"] == 2


def test_mapping_requires_assigned_platform(client):
    created = client.post("/api/components", json=definition([{"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "CONTROL"}])).get_json()
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    component = client.post("/api/nodes/mapping-node/components", json={"definition_key": created["definition_key"], "label": "Pump"}).get_json()
    url = f"/api/nodes/mapping-node/components/{component['connected_component_id']}/hardware-mapping"
    response = client.put(url, json={"mappings": [], "i2c_addresses": {}})
    assert response.status_code == 400
    assert any(x["code"] == "hardware_platform_required" for x in response.get_json()["validation_errors"])


def resource_ids(path):
    with sqlite3.connect(path) as connection:
        return dict(connection.execute(
            "SELECT resource_name,id FROM hardware_platform_resources"
        ).fetchall())


def endpoint_id(mapping, endpoint_key, interface_key=None):
    for item in mapping["interfaces_signals"]:
        if interface_key is not None and item.get("interface_key") != interface_key:
            continue
        for endpoint in item.get("endpoints", [item]):
            if endpoint["endpoint_key"] == endpoint_key:
                return endpoint["endpoint_id"]
    raise AssertionError(f"Missing endpoint {interface_key or 'direct'} / {endpoint_key}")


def mapping_url(component):
    return f"/api/nodes/mapping-node/components/{component['connected_component_id']}/hardware-mapping"


def create_component(client, definition_key, label):
    return client.post("/api/nodes/mapping-node/components", json={
        "definition_key": definition_key, "label": label,
    }).get_json()


def comprehensive_setup(client):
    structures = [
        {"kind": "protocol", "protocol": "i2c", "i2c_address_options": ["0x40", "0x41"]},
        {"kind": "protocol", "protocol": "spi"},
        {"kind": "protocol", "protocol": "uart"},
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "ALERT"},
        {"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "RESET"},
        {"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA"},
    ]
    capabilities = [
        "i2c_sda", "i2c_scl", "spi_mosi", "spi_miso", "spi_sck", "spi_cs",
        "uart_tx", "uart_rx", "digital_input", "digital_output",
    ]
    resources = [
        {"resource": f"R{number}", "capabilities": capabilities}
        for number in range(1, 9)
    ]
    created, first, mapping = node_and_component(client, definition(structures), resources)
    return created, first, mapping


def put_mapping(client, component, mappings, addresses=None):
    return client.put(mapping_url(component), json={
        "mappings": mappings, "i2c_addresses": addresses or {},
    })


def test_can_share_uses_complete_role_identity():
    from app.component_mapping import can_share

    for role in ("i2c_sda", "i2c_scl", "spi_mosi", "spi_miso", "spi_sck"):
        assert can_share({role}, {role})
    rejected = [
        ({"i2c_sda"}, {"i2c_scl"}),
        ({"i2c_sda"}, {"spi_mosi"}),
        ({"spi_mosi"}, {"spi_miso"}),
        ({"spi_sck"}, {"i2c_scl"}),
        ({"spi_cs"}, {"spi_cs"}),
        ({"uart_tx"}, {"uart_tx"}),
        ({"uart_rx"}, {"uart_rx"}),
        ({"digital_input"}, {"digital_input"}),
        ({"digital_output"}, {"digital_output"}),
        ({"digital_input", "digital_output"}, {"digital_input", "digital_output"}),
    ]
    assert all(not can_share(left, right) for left, right in rejected)


def test_same_payload_rejects_i2c_and_spi_cross_roles(client, isolated_database):
    _, component, mapping = comprehensive_setup(client)
    resources = resource_ids(isolated_database)
    response = put_mapping(client, component, [
        {"endpoint_id": endpoint_id(mapping, "sda", "i2c-1"), "resource_id": resources["R1"]},
        {"endpoint_id": endpoint_id(mapping, "scl", "i2c-1"), "resource_id": resources["R1"]},
    ], {"i2c-1": "0x40"})
    assert response.status_code == 400
    assert any(error["code"] == "resource_role_conflict"
               for error in response.get_json()["validation_errors"])

    response = put_mapping(client, component, [
        {"endpoint_id": endpoint_id(mapping, "mosi", "spi-1"), "resource_id": resources["R2"]},
        {"endpoint_id": endpoint_id(mapping, "miso", "spi-1"), "resource_id": resources["R2"]},
    ])
    assert response.status_code == 400
    assert any(error["code"] == "resource_role_conflict"
               for error in response.get_json()["validation_errors"])


def test_spi_identical_roles_share_but_cross_roles_and_cs_do_not(client, isolated_database):
    created, first, first_mapping = comprehensive_setup(client)
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    resources = resource_ids(isolated_database)

    for key, resource_name in (("mosi", "R1"), ("miso", "R2"), ("sck", "R3")):
        assert put_mapping(client, first, [{
            "endpoint_id": endpoint_id(first_mapping, key, "spi-1"),
            "resource_id": resources[resource_name],
        }]).status_code == 200
        assert put_mapping(client, second, [{
            "endpoint_id": endpoint_id(second_mapping, key, "spi-1"),
            "resource_id": resources[resource_name],
        }]).status_code == 200

    cross_role = put_mapping(client, second, [{
        "endpoint_id": endpoint_id(second_mapping, "miso", "spi-1"),
        "resource_id": resources["R3"],
    }])
    assert cross_role.status_code == 400

    assert put_mapping(client, first, [{
        "endpoint_id": endpoint_id(first_mapping, "cs", "spi-1"),
        "resource_id": resources["R4"],
    }]).status_code == 200
    assert put_mapping(client, second, [{
        "endpoint_id": endpoint_id(second_mapping, "cs", "spi-1"),
        "resource_id": resources["R4"],
    }]).status_code == 400


def test_exclusive_uart_and_direct_signal_roles_reject_duplicates(client, isolated_database):
    created, first, first_mapping = comprehensive_setup(client)
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    resources = resource_ids(isolated_database)
    cases = [
        ("tx", "uart-1", "R1"), ("rx", "uart-1", "R2"),
        ("alert", None, "R3"), ("reset", None, "R4"), ("data", None, "R5"),
    ]
    for key, interface, resource_name in cases:
        assert put_mapping(client, first, [{
            "endpoint_id": endpoint_id(first_mapping, key, interface),
            "resource_id": resources[resource_name],
        }]).status_code == 200
        duplicate = put_mapping(client, second, [{
            "endpoint_id": endpoint_id(second_mapping, key, interface),
            "resource_id": resources[resource_name],
        }])
        assert duplicate.status_code == 400
        assert any(error["code"] == "resource_role_conflict"
                   for error in duplicate.get_json()["validation_errors"])


def test_cross_protocol_roles_cannot_share_multicapability_resource(client, isolated_database):
    created, first, first_mapping = comprehensive_setup(client)
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    resources = resource_ids(isolated_database)
    i2c = [
        {"endpoint_id": endpoint_id(first_mapping, "sda", "i2c-1"), "resource_id": resources["R1"]},
        {"endpoint_id": endpoint_id(first_mapping, "scl", "i2c-1"), "resource_id": resources["R2"]},
    ]
    assert put_mapping(client, first, i2c, {"i2c-1": "0x40"}).status_code == 200
    for key, resource in (("mosi", "R1"), ("sck", "R2")):
        response = put_mapping(client, second, [{
            "endpoint_id": endpoint_id(second_mapping, key, "spi-1"),
            "resource_id": resources[resource],
        }])
        assert response.status_code == 400


def test_i2c_pair_topology_and_address_rules(client, isolated_database):
    created, first, first_mapping = comprehensive_setup(client)
    resources = resource_ids(isolated_database)
    first_payload = [
        {"endpoint_id": endpoint_id(first_mapping, "sda", "i2c-1"), "resource_id": resources["R1"]},
        {"endpoint_id": endpoint_id(first_mapping, "scl", "i2c-1"), "resource_id": resources["R2"]},
    ]
    assert put_mapping(client, first, first_payload, {"i2c-1": "0x40"}).status_code == 200

    def i2c_for(component, sda, scl, address):
        data = client.get(mapping_url(component)).get_json()
        return put_mapping(client, component, [
            {"endpoint_id": endpoint_id(data, "sda", "i2c-1"), "resource_id": resources[sda]},
            {"endpoint_id": endpoint_id(data, "scl", "i2c-1"), "resource_id": resources[scl]},
        ], {"i2c-1": address})

    same_bus = create_component(client, created["definition_key"], "Same Bus")
    assert i2c_for(same_bus, "R1", "R2", "0x41").status_code == 200
    allocation = client.get("/api/nodes/mapping-node/hardware-allocation").get_json()
    shared_roles = {
        item["resource"]: (item["state"], {entry["role"] for entry in item["allocations"]})
        for item in allocation["resources"] if item["resource"] in {"R1", "R2"}
    }
    assert shared_roles == {
        "R1": ("Shared", {"I²C SDA"}),
        "R2": ("Shared", {"I²C SCL"}),
    }
    collision = create_component(client, created["definition_key"], "Collision")
    assert any(error["code"] == "i2c_address_collision" for error in
               i2c_for(collision, "R1", "R2", "0x40").get_json()["validation_errors"])
    split_scl = create_component(client, created["definition_key"], "Split SCL")
    assert any(error["code"] == "i2c_topology_conflict" for error in
               i2c_for(split_scl, "R1", "R3", "0x40").get_json()["validation_errors"])
    split_sda = create_component(client, created["definition_key"], "Split SDA")
    assert any(error["code"] == "i2c_topology_conflict" for error in
               i2c_for(split_sda, "R3", "R2", "0x40").get_json()["validation_errors"])
    other_bus = create_component(client, created["definition_key"], "Other Bus")
    assert i2c_for(other_bus, "R3", "R4", "0x40").status_code == 200


def test_partial_mapping_states_optional_semantics_and_node_state(client, isolated_database):
    payload = definition([
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "ONE"},
        {"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "TWO"},
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "OPTIONAL", "optional": True},
    ])
    created, first, mapping = node_and_component(client, payload, [
        {"resource": "IN", "capabilities": ["digital_input"]},
        {"resource": "OUT", "capabilities": ["digital_output"]},
    ])
    resources = resource_ids(isolated_database)
    assert mapping["mapping_state"] == "Unmapped"
    assert client.get("/api/nodes/mapping-node/hardware-allocation").get_json()["mapping_state"] == "Incomplete"
    partial = put_mapping(client, first, [{
        "endpoint_id": endpoint_id(mapping, "one"), "resource_id": resources["IN"],
    }])
    assert partial.status_code == 200
    assert partial.get_json()["mapping_state"] == "Partially Mapped"
    complete = put_mapping(client, first, [
        {"endpoint_id": endpoint_id(mapping, "one"), "resource_id": resources["IN"]},
        {"endpoint_id": endpoint_id(mapping, "two"), "resource_id": resources["OUT"]},
    ])
    assert complete.get_json()["mapping_state"] == "Mapped"
    assert client.get("/api/nodes/mapping-node/hardware-allocation").get_json()["mapping_state"] == "Complete"
    second = create_component(client, created["definition_key"], "Unmapped")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Unmapped"
    assert client.get("/api/nodes/mapping-node/hardware-allocation").get_json()["mapping_state"] == "Incomplete"


def test_partial_i2c_coherence_and_address_requirement(client, isolated_database):
    payload = definition([
        {"kind": "protocol", "protocol": "i2c", "i2c_address_options": ["0x40"]},
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "ALERT"},
    ])
    _, component, mapping = node_and_component(client, payload, [
        {"resource": "SDA", "capabilities": ["i2c_sda"]},
        {"resource": "SCL", "capabilities": ["i2c_scl"]},
        {"resource": "ALERT", "capabilities": ["digital_input"]},
    ])
    resources = resource_ids(isolated_database)
    alert_only = put_mapping(client, component, [{
        "endpoint_id": endpoint_id(mapping, "alert"), "resource_id": resources["ALERT"],
    }])
    assert alert_only.status_code == 200
    assert alert_only.get_json()["mapping_state"] == "Partially Mapped"
    for key, resource in (("sda", "SDA"), ("scl", "SCL")):
        half = put_mapping(client, component, [{
            "endpoint_id": endpoint_id(mapping, key, "i2c-1"),
            "resource_id": resources[resource],
        }])
        assert half.status_code == 400
        assert any(error["code"] == "incomplete_i2c_interface"
                   for error in half.get_json()["validation_errors"])
    pair = [
        {"endpoint_id": endpoint_id(mapping, "sda", "i2c-1"), "resource_id": resources["SDA"]},
        {"endpoint_id": endpoint_id(mapping, "scl", "i2c-1"), "resource_id": resources["SCL"]},
    ]
    no_address = put_mapping(client, component, pair)
    assert any(error["code"] == "i2c_address_required"
               for error in no_address.get_json()["validation_errors"])
    full = put_mapping(client, component, pair, {"i2c-1": "0x40"})
    assert full.status_code == 200
    assert full.get_json()["mapping_state"] == "Partially Mapped"


def test_invalid_partial_update_is_atomic(client, isolated_database):
    _, component, mapping = node_and_component(client, definition([
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "ONE"},
        {"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "TWO"},
    ]), [
        {"resource": "IN", "capabilities": ["digital_input"]},
        {"resource": "OUT", "capabilities": ["digital_output"]},
    ])
    resources = resource_ids(isolated_database)
    original = [{"endpoint_id": endpoint_id(mapping, "one"), "resource_id": resources["IN"]}]
    assert put_mapping(client, component, original).status_code == 200
    invalid = put_mapping(client, component, [
        {"endpoint_id": endpoint_id(mapping, "one"), "resource_id": resources["IN"]},
        {"endpoint_id": endpoint_id(mapping, "two"), "resource_id": resources["IN"]},
    ])
    assert invalid.status_code == 400
    persisted = client.get(mapping_url(component)).get_json()
    assert persisted["mapping_state"] == "Partially Mapped"
    assert next(item for item in persisted["interfaces_signals"] if item["endpoint_key"] == "one")["mapped_resource"]["resource"] == "IN"
    assert next(item for item in persisted["interfaces_signals"] if item["endpoint_key"] == "two")["mapped_resource"] is None


def test_allocation_roles_and_dropdown_occupancy_context(client, isolated_database):
    created, first, mapping = node_and_component(client, definition([
        {"kind": "protocol", "protocol": "spi", "endpoints": ["mosi"]},
        {"kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA"},
    ]), [
        {"resource": "BUS", "capabilities": ["spi_mosi"]},
        {"resource": "IO_17", "capabilities": ["digital_input", "digital_output"]},
    ])
    resources = resource_ids(isolated_database)
    assert put_mapping(client, first, [
        {"endpoint_id": endpoint_id(mapping, "mosi", "spi-1"), "resource_id": resources["BUS"]},
        {"endpoint_id": endpoint_id(mapping, "data"), "resource_id": resources["IO_17"]},
    ]).status_code == 200
    allocation = client.get("/api/nodes/mapping-node/hardware-allocation").get_json()
    roles = {item["resource"]: item["allocations"][0]["role"] for item in allocation["resources"]}
    assert roles == {"BUS": "SPI MOSI", "IO_17": "Digital I/O"}

    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    mosi = next(endpoint for item in second_mapping["interfaces_signals"]
                for endpoint in item.get("endpoints", []) if endpoint["endpoint_key"] == "mosi")
    bus = next(resource for resource in mosi["eligible_resources"] if resource["resource"] == "BUS")
    assert bus["occupancy_state"] == "Shared"
    assert bus["occupancy_roles"] == ["SPI MOSI"]
    data = next(item for item in second_mapping["interfaces_signals"] if item.get("endpoint_key") == "data")
    assert "IO_17" not in {resource["resource"] for resource in data["eligible_resources"]}


def test_component_frontend_uses_real_accessible_behaviors_without_source_shims(client):
    library = client.get("/components").get_data(as_text=True)
    library_script = client.get("/static/components.js").get_data(as_text=True)
    detail_script = client.get("/static/component_detail.js").get_data(as_text=True)

    assert "Interfaces &amp; Signals" in library
    assert "<template><th>Interface(s)</th></template>" not in library
    assert "Compatibility contract" not in library_script
    assert "Keyboard menu compatibility" not in library_script
    assert 'trigger.setAttribute("aria-expanded", String(opening))' in library_script
    assert 'tr.classList.toggle("menu-open", opening)' in library_script
    assert 'if (event.key === "Escape") closeRowMenus();' in library_script
    assert 'select.add(new Option("Not mapped", ""))' in detail_script
    assert "resourceOptionLabel" in detail_script


def database_component_id(path, public_id):
    with sqlite3.connect(path) as connection:
        return connection.execute(
            "SELECT id FROM connected_components WHERE connected_component_id=?",
            (public_id,),
        ).fetchone()[0]


def database_endpoint_id(path, definition_key, endpoint_key, interface_key=None):
    with sqlite3.connect(path) as connection:
        return connection.execute("""SELECT endpoint.id
            FROM component_endpoints endpoint
            JOIN component_definitions definition
              ON definition.id=endpoint.component_definition_id
            LEFT JOIN component_interfaces interface
              ON interface.id=endpoint.component_interface_id
            WHERE definition.definition_key=? AND endpoint.endpoint_key=?
              AND (? IS NULL OR interface.interface_key=?)""",
            (definition_key, endpoint_key, interface_key, interface_key),
        ).fetchone()[0]


def seed_active_mapping(path, component, endpoint, resource):
    with sqlite3.connect(path) as connection:
        connection.execute("""INSERT INTO connected_component_hardware_mappings
            (connected_component_id,endpoint_id,hardware_resource_id,created_at)
            VALUES(?,?,?,?)""", (component, endpoint, resource, "2026-01-01 00:00:00"))
        connection.commit()


def seed_i2c_configuration(path, component, definition_key, address):
    with sqlite3.connect(path) as connection:
        interface_id = connection.execute("""SELECT interface.id
            FROM component_interfaces interface
            JOIN component_definitions definition
              ON definition.id=interface.component_definition_id
            WHERE definition.definition_key=? AND interface.interface_key='i2c-1'""",
            (definition_key,),
        ).fetchone()[0]
        connection.execute("""INSERT INTO connected_component_interface_configuration
            (connected_component_id,component_interface_id,i2c_address,created_at)
            VALUES(?,?,?,?)""", (component, interface_id, address, "2026-01-01 00:00:00"))
        connection.commit()


def assert_component_and_node_states(client, component, component_state, node_state):
    mapping = client.get(mapping_url(component)).get_json()
    assert mapping["mapping_state"] == component_state
    listing = client.get("/api/nodes/mapping-node/components").get_json()
    listed = next(item for item in listing
                  if item["connected_component_id"] == component["connected_component_id"])
    assert listed["mapping_state"] == component_state
    allocation = client.get("/api/nodes/mapping-node/hardware-allocation").get_json()
    assert allocation["mapping_state"] == node_state


def i2c_invalid_setup(client, isolated_database, options=None):
    structure = {"kind": "protocol", "protocol": "i2c"}
    if options is not None:
        structure["i2c_address_options"] = options
    created, component, mapping = node_and_component(client, definition([structure]), [
        {"resource": "SDA_A", "capabilities": ["i2c_sda"]},
        {"resource": "SCL_A", "capabilities": ["i2c_scl"]},
        {"resource": "SDA_B", "capabilities": ["i2c_sda"]},
        {"resource": "SCL_B", "capabilities": ["i2c_scl"]},
    ])
    return created, component, mapping, resource_ids(isolated_database)


def test_persisted_incompatible_resource_is_derived_invalid(client, isolated_database):
    _, component, mapping = node_and_component(client, definition([{
        "kind": "direct_signal", "signal_type": "digital_io", "endpoint_label": "DATA",
    }]), [{"resource": "ADC_ONLY", "capabilities": ["adc"]}])
    seed_active_mapping(
        isolated_database,
        database_component_id(isolated_database, component["connected_component_id"]),
        endpoint_id(mapping, "data"),
        resource_ids(isolated_database)["ADC_ONLY"],
    )
    assert_component_and_node_states(client, component, "Invalid", "Invalid")


def test_persisted_wrong_endpoint_and_platform_resource_are_invalid(
        client, isolated_database):
    first = client.post("/api/components", json=definition([{
        "kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "FIRST",
    }])).get_json()
    second = client.post("/api/components", json=definition([{
        "kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "SECOND",
    }])).get_json()
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    assigned = platform(client, [{"resource": "OWN", "capabilities": ["digital_output"]}])
    client.put("/api/nodes/mapping-node/hardware-platform", json={
        "hardware_platform_id": assigned["hardware_platform_id"],
    })
    foreign = platform(client, [{"resource": "FOREIGN", "capabilities": ["digital_output"]}])
    assert foreign["hardware_platform_id"] != assigned["hardware_platform_id"]
    component = create_component(client, first["definition_key"], "Physical")
    component_db_id = database_component_id(
        isolated_database, component["connected_component_id"]
    )
    seed_active_mapping(
        isolated_database, component_db_id,
        database_endpoint_id(isolated_database, second["definition_key"], "second"),
        resource_ids(isolated_database)["OWN"],
    )
    assert_component_and_node_states(client, component, "Invalid", "Invalid")

    with sqlite3.connect(isolated_database) as connection:
        connection.execute(
            "DELETE FROM connected_component_hardware_mappings WHERE connected_component_id=?",
            (component_db_id,),
        )
        connection.commit()
    seed_active_mapping(
        isolated_database, component_db_id,
        database_endpoint_id(isolated_database, first["definition_key"], "first"),
        resource_ids(isolated_database)["FOREIGN"],
    )
    assert_component_and_node_states(client, component, "Invalid", "Invalid")

    unrelated_i2c = client.post("/api/components", json=definition([{
        "kind": "protocol", "protocol": "i2c",
    }])).get_json()
    with sqlite3.connect(isolated_database) as connection:
        connection.execute(
            "DELETE FROM connected_component_hardware_mappings WHERE connected_component_id=?",
            (component_db_id,),
        )
        interface_id = connection.execute("""SELECT interface.id
            FROM component_interfaces interface
            JOIN component_definitions definition
              ON definition.id=interface.component_definition_id
            WHERE definition.definition_key=?""",
            (unrelated_i2c["definition_key"],),
        ).fetchone()[0]
        connection.execute("""INSERT INTO connected_component_interface_configuration
            (connected_component_id,component_interface_id,i2c_address,created_at)
            VALUES(?,?,?,?)""", (
                component_db_id, interface_id, 0x40, "2026-01-01 00:00:00",
            ))
        connection.commit()
    assert_component_and_node_states(client, component, "Invalid", "Invalid")


def test_persisted_exclusive_duplicate_and_cross_role_sharing_are_invalid(
        client, isolated_database):
    created, first, mapping = comprehensive_setup(client)
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    resources = resource_ids(isolated_database)
    first_db = database_component_id(isolated_database, first["connected_component_id"])
    second_db = database_component_id(isolated_database, second["connected_component_id"])

    seed_active_mapping(isolated_database, first_db, endpoint_id(mapping, "reset"), resources["R1"])
    seed_active_mapping(isolated_database, second_db, endpoint_id(second_mapping, "reset"), resources["R1"])
    assert_component_and_node_states(client, first, "Invalid", "Invalid")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Invalid"

    with sqlite3.connect(isolated_database) as connection:
        connection.execute("DELETE FROM connected_component_hardware_mappings")
        connection.commit()
    seed_active_mapping(
        isolated_database, first_db, endpoint_id(mapping, "mosi", "spi-1"), resources["R2"]
    )
    seed_active_mapping(
        isolated_database, second_db, endpoint_id(second_mapping, "sck", "spi-1"), resources["R2"]
    )
    assert_component_and_node_states(client, first, "Invalid", "Invalid")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Invalid"


def test_persisted_i2c_half_pair_and_configuration_mismatch_are_invalid(
        client, isolated_database):
    created, component, mapping, resources = i2c_invalid_setup(client, isolated_database)
    component_db = database_component_id(isolated_database, component["connected_component_id"])
    seed_active_mapping(
        isolated_database, component_db, endpoint_id(mapping, "sda", "i2c-1"),
        resources["SDA_A"],
    )
    assert_component_and_node_states(client, component, "Invalid", "Invalid")

    with sqlite3.connect(isolated_database) as connection:
        connection.execute("DELETE FROM connected_component_hardware_mappings")
        connection.commit()
    seed_i2c_configuration(isolated_database, component_db, created["definition_key"], 0x40)
    assert_component_and_node_states(client, component, "Invalid", "Invalid")

    with sqlite3.connect(isolated_database) as connection:
        connection.execute("DELETE FROM connected_component_interface_configuration")
        connection.commit()
    seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "sda", "i2c-1"), resources["SDA_A"])
    seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "scl", "i2c-1"), resources["SCL_A"])
    assert_component_and_node_states(client, component, "Invalid", "Invalid")


def test_persisted_i2c_address_range_and_definition_options_are_invalid(
        client, isolated_database):
    created, component, mapping, resources = i2c_invalid_setup(
        client, isolated_database, ["0x76", "0x77"]
    )
    component_db = database_component_id(isolated_database, component["connected_component_id"])
    seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "sda", "i2c-1"), resources["SDA_A"])
    seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "scl", "i2c-1"), resources["SCL_A"])
    seed_i2c_configuration(isolated_database, component_db, created["definition_key"], 0x07)
    for address in (0x07, 0x78, 0x40):
        with sqlite3.connect(isolated_database) as connection:
            connection.execute("""UPDATE connected_component_interface_configuration
                SET i2c_address=? WHERE connected_component_id=? AND active=1""",
                (address, component_db))
            connection.commit()
        assert_component_and_node_states(client, component, "Invalid", "Invalid")


def test_persisted_same_bus_collision_is_invalid_but_valid_i2c_controls_remain_mapped(
        client, isolated_database):
    created, first, first_mapping, resources = i2c_invalid_setup(client, isolated_database)
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()

    def seed_pair(component, mapping, sda, scl, address):
        component_db = database_component_id(
            isolated_database, component["connected_component_id"]
        )
        seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "sda", "i2c-1"), resources[sda])
        seed_active_mapping(isolated_database, component_db, endpoint_id(mapping, "scl", "i2c-1"), resources[scl])
        seed_i2c_configuration(isolated_database, component_db, created["definition_key"], address)

    seed_pair(first, first_mapping, "SDA_A", "SCL_A", 0x40)
    seed_pair(second, second_mapping, "SDA_A", "SCL_A", 0x40)
    assert_component_and_node_states(client, first, "Invalid", "Invalid")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Invalid"

    with sqlite3.connect(isolated_database) as connection:
        second_db = database_component_id(isolated_database, second["connected_component_id"])
        connection.execute("DELETE FROM connected_component_hardware_mappings WHERE connected_component_id=?", (second_db,))
        connection.execute("DELETE FROM connected_component_interface_configuration WHERE connected_component_id=?", (second_db,))
        connection.commit()
    seed_pair(second, second_mapping, "SDA_B", "SCL_B", 0x40)
    assert_component_and_node_states(client, first, "Mapped", "Complete")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Mapped"

    with sqlite3.connect(isolated_database) as connection:
        second_db = database_component_id(isolated_database, second["connected_component_id"])
        connection.execute("DELETE FROM connected_component_hardware_mappings WHERE connected_component_id=?", (second_db,))
        connection.execute("DELETE FROM connected_component_interface_configuration WHERE connected_component_id=?", (second_db,))
        connection.commit()
    seed_pair(second, second_mapping, "SDA_A", "SCL_A", 0x41)
    assert_component_and_node_states(client, first, "Mapped", "Complete")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Mapped"


def test_persisted_optional_mapping_invalidity_and_state_precedence(
        client, isolated_database):
    created, first, mapping = node_and_component(client, definition([
        {"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "REQUIRED"},
        {"kind": "direct_signal", "signal_type": "digital_output", "endpoint_label": "SECOND"},
        {"kind": "direct_signal", "signal_type": "digital_input", "endpoint_label": "OPTIONAL", "optional": True},
    ]), [
        {"resource": "OUT_A", "capabilities": ["digital_output"]},
        {"resource": "OUT_B", "capabilities": ["digital_output"]},
        {"resource": "ADC", "capabilities": ["adc"]},
    ])
    resources = resource_ids(isolated_database)
    assert_component_and_node_states(client, first, "Unmapped", "Incomplete")
    first_db = database_component_id(isolated_database, first["connected_component_id"])
    seed_active_mapping(isolated_database, first_db, endpoint_id(mapping, "required"), resources["OUT_A"])
    assert_component_and_node_states(client, first, "Partially Mapped", "Incomplete")
    seed_active_mapping(isolated_database, first_db, endpoint_id(mapping, "second"), resources["OUT_B"])
    assert_component_and_node_states(client, first, "Mapped", "Complete")
    seed_active_mapping(isolated_database, first_db, endpoint_id(mapping, "optional"), resources["ADC"])
    assert_component_and_node_states(client, first, "Invalid", "Invalid")

    second = create_component(client, created["definition_key"], "Unmapped")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Unmapped"
    assert client.get("/api/nodes/mapping-node/hardware-allocation").get_json()["mapping_state"] == "Invalid"


def test_valid_shared_spi_bus_remains_mapped_and_complete(client, isolated_database):
    created, first, first_mapping = node_and_component(client, definition([{
        "kind": "protocol", "protocol": "spi",
    }]), [
        {"resource": "MOSI", "capabilities": ["spi_mosi"]},
        {"resource": "MISO", "capabilities": ["spi_miso"]},
        {"resource": "SCK", "capabilities": ["spi_sck"]},
        {"resource": "CS_A", "capabilities": ["spi_cs"]},
        {"resource": "CS_B", "capabilities": ["spi_cs"]},
    ])
    second = create_component(client, created["definition_key"], "Second")
    second_mapping = client.get(mapping_url(second)).get_json()
    resources = resource_ids(isolated_database)
    first_db = database_component_id(isolated_database, first["connected_component_id"])
    second_db = database_component_id(isolated_database, second["connected_component_id"])
    shared = (("mosi", "MOSI"), ("miso", "MISO"), ("sck", "SCK"))
    for key, resource in shared:
        seed_active_mapping(isolated_database, first_db, endpoint_id(first_mapping, key, "spi-1"), resources[resource])
        seed_active_mapping(isolated_database, second_db, endpoint_id(second_mapping, key, "spi-1"), resources[resource])
    seed_active_mapping(isolated_database, first_db, endpoint_id(first_mapping, "cs", "spi-1"), resources["CS_A"])
    seed_active_mapping(isolated_database, second_db, endpoint_id(second_mapping, "cs", "spi-1"), resources["CS_B"])
    assert_component_and_node_states(client, first, "Mapped", "Complete")
    assert client.get(mapping_url(second)).get_json()["mapping_state"] == "Mapped"


def test_dangling_endpoint_mapping_keeps_allocation_readable_and_invalid(
        client, isolated_database):
    _, component, mapping = node_and_component(client, definition([{
        "kind": "direct_signal", "signal_type": "digital_output",
        "endpoint_label": "CONTROL",
    }]), [{"resource": "OUTPUT", "capabilities": ["digital_output"]}])
    endpoint = mapping["interfaces_signals"][0]
    resource = endpoint["eligible_resources"][0]
    response = put_mapping(client, component, [{
        "endpoint_id": endpoint["endpoint_id"],
        "resource_id": resource["resource_id"],
    }])
    assert response.status_code == 200

    with sqlite3.connect(isolated_database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        persisted_before = connection.execute("""SELECT id,connected_component_id,
                endpoint_id,hardware_resource_id,active,created_at,removed_at
            FROM connected_component_hardware_mappings WHERE active=1""").fetchone()
        connection.execute(
            "DELETE FROM component_endpoints WHERE id=?", (endpoint["endpoint_id"],)
        )
        connection.commit()

    mapping_response = client.get(mapping_url(component))
    assert mapping_response.status_code == 200
    assert mapping_response.get_json()["mapping_state"] == "Invalid"

    allocation_response = client.get("/api/nodes/mapping-node/hardware-allocation")
    assert allocation_response.status_code == 200
    allocation = allocation_response.get_json()
    assert allocation["mapping_state"] == "Invalid"
    assert set(allocation) == {"mapping_state", "used", "shared", "free", "resources"}
    output = next(item for item in allocation["resources"]
                  if item["resource"] == "OUTPUT")
    assert output["state"] == "Allocated"
    assert output["allocations"] == [{
        "role": "Invalid mapping",
        "interface_signal": "—",
        "connected_component_id": component["connected_component_id"],
        "connected_component": "Outside THP",
    }]

    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute(
            "SELECT 1 FROM component_endpoints WHERE id=?", (endpoint["endpoint_id"],)
        ).fetchone() is None
        persisted_after = connection.execute("""SELECT id,connected_component_id,
                endpoint_id,hardware_resource_id,active,created_at,removed_at
            FROM connected_component_hardware_mappings WHERE active=1""").fetchone()
    assert persisted_after == persisted_before


def test_hardware_allocation_uses_generic_natural_resource_order(client):
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    board = platform(client, [
        {"resource": name, "capabilities": ["digital_output"]}
        for name in ("GPIO10", "GPIO2", "GPIO1", "A10", "A2", "A1",
                     "IO_17", "IO_2", "SENSOR_SDA")
    ])
    response = client.put("/api/nodes/mapping-node/hardware-platform", json={
        "hardware_platform_id": board["hardware_platform_id"],
    })
    assert response.status_code == 200

    allocation = client.get(
        "/api/nodes/mapping-node/hardware-allocation"
    ).get_json()
    assert [item["resource"] for item in allocation["resources"]] == [
        "A1", "A2", "A10", "GPIO1", "GPIO2", "GPIO10",
        "IO_2", "IO_17", "SENSOR_SDA",
    ]


def test_legacy_dht22_migration_uses_data_endpoint(client, isolated_database):
    with sqlite3.connect(isolated_database) as connection:
        now = database.now_string()
        connection.execute("""INSERT INTO component_definitions
            (definition_key,display_name,manufacturer,model,component_class,
             created_at,updated_at)
            VALUES('legacy-real-dht','Legacy Temperature Sensor','Aosong',
                   'DHT22 / AM2302','sensor',?,?)""", (now, now))
        definition_id = connection.execute(
            "SELECT id FROM component_definitions WHERE definition_key='legacy-real-dht'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO component_interface_requirements VALUES(?, 'digital_signal')",
            (definition_id,),
        )
        connection.executemany("""INSERT INTO component_capabilities
            SELECT ?,id FROM capabilities WHERE capability_key=?""", [
                (definition_id, "temperature_measurement"),
                (definition_id, "humidity_measurement"),
            ])
        connection.commit()

    database.init_db()
    migrated = client.get("/api/components/legacy-real-dht").get_json()
    endpoint = migrated["interfaces_signals"][0]
    assert endpoint["endpoint_key"] == "data"
    assert endpoint["endpoint_label"] == "DATA"
    assert endpoint["signal_type"] == "digital_io"
    assert endpoint["required_capabilities"] == ["digital_input", "digital_output"]


def test_migration_corrects_only_generated_dht22_signal_in_place(
        client, isolated_database):
    database.update_device_metadata("mapping-node", {"node_type": "controller"})
    board = platform(client, [{
        "resource": "DHT_DATA",
        "capabilities": ["digital_input", "digital_output"],
    }])
    assert client.put("/api/nodes/mapping-node/hardware-platform", json={
        "hardware_platform_id": board["hardware_platform_id"],
    }).status_code == 200
    component = client.post("/api/nodes/mapping-node/components", json={
        "definition_key": "aosong-dht22", "label": "DHT22",
    }).get_json()
    mapping = client.get(mapping_url(component)).get_json()
    endpoint = mapping["interfaces_signals"][0]
    resource = endpoint["eligible_resources"][0]
    assert put_mapping(client, component, [{
        "endpoint_id": endpoint["endpoint_id"],
        "resource_id": resource["resource_id"],
    }]).status_code == 200

    unrelated = client.post("/api/components", json=definition([{
        "kind": "direct_signal", "signal_type": "digital_io",
        "endpoint_label": "SIGNAL",
    }])).get_json()
    with sqlite3.connect(isolated_database) as connection:
        connection.execute("""UPDATE component_endpoints
            SET endpoint_key='signal',endpoint_label='SIGNAL' WHERE id=?""",
            (endpoint["endpoint_id"],),
        )
        connection.commit()

    database.init_db()
    with sqlite3.connect(isolated_database) as connection:
        corrected = connection.execute("""SELECT id,endpoint_key,endpoint_label
            FROM component_endpoints WHERE id=?""", (endpoint["endpoint_id"],)).fetchone()
        mapped_endpoint_id = connection.execute("""SELECT endpoint_id
            FROM connected_component_hardware_mappings WHERE active=1""").fetchone()[0]
    assert corrected == (endpoint["endpoint_id"], "data", "DATA")
    assert mapped_endpoint_id == endpoint["endpoint_id"]
    untouched = client.get(
        f"/api/components/{unrelated['definition_key']}"
    ).get_json()["interfaces_signals"][0]
    assert (untouched["endpoint_key"], untouched["endpoint_label"]) == (
        "signal", "SIGNAL",
    )


def test_compact_signal_labels_selector_vocabulary_and_state_classes():
    components_source = open("static/components.js", encoding="utf-8").read()
    technical_source = open("static/node_technical.js", encoding="utf-8").read()
    detail_source = open("static/component_detail.js", encoding="utf-8").read()
    styles = open("static/style.css", encoding="utf-8").read()

    for machine_type, full_label, compact_label in (
        ("analog_input", "ADC — Analog Input to Node", "ADC"),
        ("analog_output", "DAC — Analog Output from Node", "DAC"),
        ("digital_input", "Digital Input — Input to Node", "Digital Input"),
        ("digital_output", "Digital Output — Output from Node", "Digital Output"),
        ("digital_io", "Digital I/O — Bidirectional", "Digital I/O"),
        ("pwm_output", "PWM — Output from Node", "PWM"),
    ):
        assert f'["{machine_type}", "{full_label}"]' in components_source
        assert f'{machine_type}: "{compact_label}"' in components_source
        assert f'{machine_type}:"{compact_label}"' in technical_source
    assert 'return `${type}: ${interfaceSignal.endpoint_label}`' in components_source
    assert 'return `${type}: ${entry.endpoint_label}`' in technical_source
    assert '.join(" | ")' in components_source
    assert '.join(" | ")' in technical_source

    for state, css_class in (
        ("Mapped", "state-success"), ("Complete", "state-success"),
        ("Partially Mapped", "state-warning"), ("Incomplete", "state-warning"),
        ("Unmapped", "state-danger"), ("Invalid", "state-danger"),
    ):
        assert state in technical_source
        assert css_class in technical_source
        assert state in detail_source or state in technical_source
    assert ".state-success" in styles
    assert ".state-warning" in styles
    assert ".state-danger" in styles
    assert ".component-table td:nth-last-child(2)" not in styles


def test_hardware_allocation_pill_and_filter_presentation_contract():
    technical_source = open("static/node_technical.js", encoding="utf-8").read()
    styles = open("static/style.css", encoding="utf-8").read()

    assert "link.className='usage-count-link'" in technical_source
    assert "link.href=`/nodes/${encodeURIComponent(nodeId)}/components/" in technical_source
    assert "if(!allocations.length)td.textContent='—'" in technical_source
    assert "allocationFilter='all'" in technical_source
    assert "allocationFilter='used'" in technical_source
    assert ".filter-buttons button { background:#263f4a;color:#fff; }" in styles
    assert ".filter-buttons .active,.filter-buttons .active:hover { background:#f8fafc;color:#111827; }" in styles
