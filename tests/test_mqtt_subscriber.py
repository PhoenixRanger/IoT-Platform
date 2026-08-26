import json
import sqlite3
from types import SimpleNamespace

import pytest

from app.mqtt_subscriber import on_message, parse_reading_payload


def parse(payload):
    return parse_reading_payload(json.dumps(payload))


def provision(client, node_id="node-a", definition_key="aosong-dht22"):
    from app.database import save_measurements
    save_measurements(node_id, {"temperature": 1})
    component = client.post(f"/api/nodes/{node_id}/components", json={
        "definition_key": definition_key, "label": "Sensor"
    }).get_json()
    return component["capability_instances"]


def test_instance_packet_schema_and_capability_metadata_are_separate():
    node, metadata, reading = parse({
        "node_id": "node-a", "instance_id": "ci_0123456789", "value": 24.8, "unit": "C"
    })
    assert node == "node-a"
    assert metadata == {}
    assert reading == {"instance_id": "ci_0123456789", "value": 24.8, "unit": "C"}
    node, metadata, reading = parse({"device_id": "node-a", "capabilities": ["wifi", "wifi"]})
    assert metadata == {"capabilities": ["wifi"]}
    assert reading is None


@pytest.mark.parametrize("payload", [
    {}, {"node_id": ""}, {"node_id": "   "}, {"node_id": "node"},
    {"node_id": "node", "outside_temperature": 2},
    {"node_id": "node", "instance_id": "ci_0123456789", "value": 2},
    {"node_id": "node", "instance_id": "ci_0123456789", "value": "24.8", "unit": "C"},
    {"node_id": "node", "instance_id": "ci_0123456789", "value": None, "unit": "C"},
    {"node_id": "node", "instance_id": "ci_0123456789", "value": True, "unit": "C"},
    {"node_id": "node", "instance_id": "ci_0123456789", "value": float("inf"), "unit": "C"},
])
def test_legacy_incomplete_and_invalid_packets_are_rejected(payload):
    with pytest.raises(ValueError):
        parse(payload)


def test_valid_instance_is_persisted_and_dashboard_metadata_renames(client, isolated_database):
    instances = provision(client)
    temperature = next(item for item in instances if item["capability_key"] == "temperature_measurement")
    payload = json.dumps({"node_id": "node-a", "instance_id": temperature["capability_instance_id"],
                          "value": 22.5, "unit": "C"}).encode()
    on_message(None, None, SimpleNamespace(payload=payload, topic="sensors/node-a/readings"))
    readings = client.get("/api/readings?node_id=node-a").get_json()
    assert readings[-1][temperature["capability_instance_id"]] == 22.5
    assert readings[-1]["_units"][temperature["capability_instance_id"]] == "C"
    metadata = client.get("/api/nodes/node-a/capability-instances").get_json()
    assert all("unit" not in item for item in metadata)

    # The same Generic Capability may report a different runtime unit; neither
    # persistence nor presentation metadata replaces it with an assumed unit.
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "node_id": "node-a", "instance_id": temperature["capability_instance_id"],
        "value": 72.5, "unit": "F",
    }).encode(), topic="sensors/node-a/readings"))
    latest = client.get("/api/readings?node_id=node-a").get_json()[-1]
    assert latest[temperature["capability_instance_id"]] == 72.5
    assert latest["_units"][temperature["capability_instance_id"]] == "F"
    dashboard_script = client.get("/static/script.js").get_data(as_text=True)
    assert 'reading?._units?.[sensorType]' in dashboard_script
    assert 'instanceMetadata[sensorType].unit' not in dashboard_script
    renamed = client.patch(f"/api/nodes/node-a/capability-instances/{temperature['capability_instance_id']}",
                           json={"label": "North Greenhouse Air"}).get_json()
    assert renamed["label"] == "North Greenhouse Air"
    assert "unit" not in renamed
    assert client.get("/api/readings?node_id=node-a").get_json()[-1]["_units"][temperature["capability_instance_id"]] == "F"
    with sqlite3.connect(isolated_database) as connection:
        row = connection.execute("SELECT capability_instance_id, sensor_type FROM measurements WHERE capability_instance_id IS NOT NULL").fetchone()
    assert row == (temperature["capability_instance_id"], "temperature_measurement")


def test_unknown_malformed_cross_node_and_removed_instances_rejected(client, isolated_database, caplog):
    a = provision(client, "node-a")[0]
    provision(client, "node-b")
    packets = [
        {"node_id": "node-a", "instance_id": "ci_bad", "value": 1, "unit": "%"},
        {"node_id": "node-a", "instance_id": "ci_0000000000", "value": 1, "unit": "%"},
        {"node_id": "node-b", "instance_id": a["capability_instance_id"], "value": 1, "unit": "%"},
    ]
    for packet in packets:
        on_message(None, None, SimpleNamespace(payload=json.dumps(packet).encode(), topic="test"))
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM measurements WHERE capability_instance_id IS NOT NULL").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM component_capability_instances").fetchone()[0] == 4
    assert "validation failed" in caplog.text


def test_removed_instance_is_rejected(client, isolated_database, caplog):
    from app.database import save_measurements

    save_measurements("node-a", {"temperature": 1})
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "aosong-dht22", "label": "Retired Sensor",
    }).get_json()
    instance_id = component["capability_instances"][0]["capability_instance_id"]
    assert client.delete(
        f"/api/nodes/node-a/components/{component['connected_component_id']}"
    ).status_code == 200
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "node_id": "node-a", "instance_id": instance_id, "value": 20, "unit": "C",
    }).encode(), topic="test"))
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute("""SELECT COUNT(*) FROM measurements
            WHERE capability_instance_id = ?""", (instance_id,)).fetchone()[0] == 0
    assert "Unknown or inactive capability instance ID" in caplog.text


def test_repeated_capabilities_are_independent_streams(client):
    first = provision(client, "node-a", "generic-analog-soil-moisture-sensor")[0]
    second = client.post("/api/nodes/node-a/components", json={
        "definition_key": "generic-analog-soil-moisture-sensor", "label": "Probe B"
    }).get_json()["capability_instances"][0]
    assert first["capability_instance_id"] != second["capability_instance_id"]
    for instance, value in ((first, 31), (second, 27)):
        on_message(None, None, SimpleNamespace(payload=json.dumps({
            "node_id": "node-a", "instance_id": instance["capability_instance_id"],
            "value": value, "unit": "%"}).encode(), topic="test"))
    readings = client.get("/api/readings?node_id=node-a").get_json()
    assert next(row[first["capability_instance_id"]] for row in readings if first["capability_instance_id"] in row) == 31
    assert next(row[second["capability_instance_id"]] for row in readings if second["capability_instance_id"] in row) == 27


@pytest.mark.parametrize("field,value", [
    ("firmware_name", 1), ("firmware_version", None), ("hardware_model", " "),
    ("ota_hostname", False), ("node_type", 3.2),
])
def test_malformed_device_metadata_is_rejected(field, value):
    with pytest.raises(ValueError, match=f"Invalid metadata value for {field}"):
        parse({"node_id": "node-a", "capabilities": ["wifi"], field: value})


def test_device_metadata_and_instance_telemetry_update_only_device_owned_fields(client):
    from app.database import get_node, update_node_registry

    instance = provision(client)[0]
    update_node_registry("node-a", {
        "name": "Server Name", "location": "Server Location", "category": "Climate",
        "latitude": 51.5, "longitude": -0.1, "enabled": False,
    })
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "node_id": "node-a", "instance_id": instance["capability_instance_id"],
        "value": 44, "unit": "%", "firmware_name": "environment-node",
        "firmware_version": "1.2.3", "hardware_model": "esp32",
        "ota_hostname": "node-a", "node_type": "field-node",
        "name": "Device Name", "location": "Device Location", "category": "Device Category",
        "latitude": 0, "longitude": 0, "enabled": True,
    }).encode(), topic="test"))
    node = get_node("node-a")
    assert {key: node[key] for key in ("name", "location", "category", "latitude", "longitude", "enabled")} == {
        "name": "Server Name", "location": "Server Location", "category": "Climate",
        "latitude": 51.5, "longitude": -0.1, "enabled": False,
    }
    assert (node["firmware_name"], node["firmware_version"], node["hardware_model"],
            node["ota_hostname"], node["node_type"]) == (
        "environment-node", "1.2.3", "esp32", "node-a", "field-node")


@pytest.mark.parametrize("capabilities", ["wifi", [1], [""], None])
def test_malformed_capability_reports_are_rejected(capabilities):
    with pytest.raises(ValueError, match="capabilities"):
        parse({"device_id": "node-a", "capabilities": capabilities})


def test_capability_only_reports_are_deduplicated_and_independent(client):
    from app.database import get_node_capabilities

    instance = provision(client)[0]
    report = SimpleNamespace(payload=json.dumps({
        "device_id": "node-a",
        "capabilities": ["wifi", "temperature_measurement", "wifi"],
    }).encode(), topic="test")
    on_message(None, None, report)
    before = get_node_capabilities("node-a")
    assert [item["capability_key"] for item in before["reported"]] == ["temperature_measurement", "wifi"]
    assert {item["capability_key"]: item["count"] for item in before["expected"]} == {
        "humidity_measurement": 1, "temperature_measurement": 1,
    }
    client.patch(f"/api/nodes/node-a/capability-instances/{instance['capability_instance_id']}",
                 json={"label": "Renamed"})
    after = get_node_capabilities("node-a")
    assert after["expected"] == before["expected"]
    assert after["reported"] == before["reported"]


def test_unknown_reported_capability_preserves_previous_set_and_registry(isolated_database, caplog):
    from app.database import get_capabilities, get_node_capabilities, replace_reported_capabilities

    replace_reported_capabilities("node-a", ["wifi"])
    registered = get_capabilities()
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "device_id": "node-a", "capabilities": ["unregistered_capability"],
    }).encode(), topic="test"))
    assert get_capabilities() == registered
    assert [item["capability_key"] for item in get_node_capabilities("node-a")["reported"]] == ["wifi"]
    assert "Unknown capability key" in caplog.text


@pytest.mark.parametrize("field,value", [
    ("rssi", "strong"), ("rssi", True), ("rssi", float("inf")),
    ("uptime_seconds", None), ("uptime_seconds", float("nan")),
])
def test_invalid_node_diagnostics_are_rejected(field, value):
    with pytest.raises(ValueError, match=f"Invalid diagnostic value for {field}"):
        parse({"node_id": "node-a", "instance_id": "ci_0123456789",
               "value": 1, "unit": "C", field: value})


def test_diagnostics_remain_node_measurements_and_do_not_create_instances(client, isolated_database):
    instance = provision(client)[0]
    with sqlite3.connect(isolated_database) as connection:
        before = connection.execute("SELECT COUNT(*) FROM component_capability_instances").fetchone()[0]
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "node_id": "node-a", "instance_id": instance["capability_instance_id"],
        "value": 21, "unit": "C", "rssi": -61, "uptime_seconds": 418,
    }).encode(), topic="test"))
    readings = client.get("/api/readings?node_id=node-a").get_json()[-1]
    assert readings["rssi"] == -61
    assert readings["uptime_seconds"] == 418
    assert readings["_units"] == {instance["capability_instance_id"]: "C"}
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM component_capability_instances").fetchone()[0] == before
        diagnostic_rows = connection.execute("""SELECT sensor_type, capability_instance_id
            FROM measurements WHERE sensor_type IN ('rssi', 'uptime_seconds') ORDER BY sensor_type""").fetchall()
    assert diagnostic_rows == [("rssi", None), ("uptime_seconds", None)]
