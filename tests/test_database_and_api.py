import sqlite3
from importlib import import_module

from app.database import SENSOR_UNITS, get_nodes, save_measurements


NEW_SENSOR_UNITS = {
    "outside_temperature": "°C",
    "outside_humidity": "%",
    "outside_pressure": "hPa",
    "enclosure_temperature": "°C",
    "enclosure_humidity": "%",
    "enclosure_pressure": "hPa",
}


def test_new_sensor_types_have_correct_units():
    for sensor_type, unit in NEW_SENSOR_UNITS.items():
        assert SENSOR_UNITS[sensor_type] == unit


def test_all_valid_readings_are_stored_and_node_is_registered(isolated_database):
    readings = {
        "outside_temperature": 24.8,
        "outside_humidity": 61.2,
        "outside_pressure": 1009.4,
        "enclosure_temperature": 31.5,
        "enclosure_humidity": 42.1,
        "enclosure_pressure": 1008.9,
        "rssi": -61,
        "uptime_seconds": 418,
    }

    saved = save_measurements("irrigation_controller_001", readings)

    assert len(saved) == len(readings)
    assert {item["sensor_type"]: item["unit"] for item in saved} == {
        **NEW_SENSOR_UNITS,
        "rssi": "dBm",
        "uptime_seconds": "s",
    }
    assert [node["node_id"] for node in get_nodes()] == ["irrigation_controller_001"]

    with sqlite3.connect(isolated_database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]
        sensor_count = connection.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]
    assert count == len(readings)
    assert sensor_count == len(readings)


def test_desk_node_behavior_remains_compatible(client):
    response = client.post("/api/data", json={
        "node_id": "environment_node_001",
        "readings": {"temperature": 23.5, "humidity": 48.0},
    })

    assert response.status_code == 200
    assert response.get_json()["status"] == "saved"
    readings = client.get("/api/readings?node_id=environment_node_001").get_json()
    assert readings[0]["temperature"] == 23.5
    assert readings[0]["humidity"] == 48.0


def test_generic_and_configured_default_node(client, monkeypatch):
    from app import database
    from app.config import DEFAULT_NODE_ID

    assert DEFAULT_NODE_ID == "environment_node_001"

    configured_node = "configured_node_001"
    routes = import_module("app.routes")
    monkeypatch.setattr(database, "DEFAULT_NODE_ID", configured_node)
    monkeypatch.setattr(routes, "DEFAULT_NODE_ID", configured_node)
    save_measurements(configured_node, {"temperature": 21.5})

    assert database.get_recent_measurements()[0]["node_id"] == configured_node
    assert client.get("/api/readings").get_json()[0]["node_id"] == configured_node
    assert client.get("/api/node-status").get_json()["node_id"] == configured_node


def test_explicit_node_id_overrides_configured_default(client, monkeypatch):
    routes = import_module("app.routes")

    monkeypatch.setattr(routes, "DEFAULT_NODE_ID", "configured_node_001")
    save_measurements("explicit_node_001", {"temperature": 22.5})

    readings = client.get("/api/readings?node_id=explicit_node_001").get_json()
    status = client.get("/api/node-status?node_id=explicit_node_001").get_json()
    assert readings[0]["node_id"] == "explicit_node_001"
    assert status["node_id"] == "explicit_node_001"


def test_api_exposes_dual_climate_readings(client):
    payload = {
        "outside_temperature": 24.8,
        "outside_humidity": 61.2,
        "outside_pressure": 1009.4,
        "enclosure_temperature": 31.5,
        "enclosure_humidity": 42.1,
    }
    response = client.post("/api/data", json={
        "node_id": "irrigation_controller_001",
        "readings": payload,
    })
    assert response.status_code == 200

    readings = client.get(
        "/api/readings?node_id=irrigation_controller_001"
    ).get_json()
    assert readings == [{
        "node_id": "irrigation_controller_001",
        "timestamp": readings[0]["timestamp"],
        **payload,
    }]

    nodes = client.get("/api/nodes").get_json()
    assert nodes[0]["node_id"] == "irrigation_controller_001"


def test_dashboard_provides_dual_climate_groups_and_labels(client):
    page = client.get("/")
    assert page.status_code == 200
    assert b"Outside Conditions" in page.data
    assert b"Enclosure Conditions" in page.data
    assert b"Node Telemetry" in page.data

    script = client.get("/static/script.js")
    assert script.status_code == 200
    assert b"Outside Air Pressure" in script.data
    assert b"Enclosure Air Pressure" in script.data


def test_metadata_is_persisted_and_updated(client):
    from app.database import get_node, update_node_metadata

    update_node_metadata("node_001", {
        "firmware_name": "environment-node",
        "firmware_version": "1.0.0",
        "hardware_model": "az-delivery-esp32-devkitc-v2",
        "hardware_revision": "prototype-a",
        "ota_hostname": "node-001",
    })
    update_node_metadata("node_001", {"firmware_version": "1.0.1"})
    node = get_node("node_001")
    assert node["firmware_version"] == "1.0.1"
    assert node["hardware_model"] == "az-delivery-esp32-devkitc-v2"


def test_node_details_api_includes_metadata_and_latest_runtime(client):
    from app.database import update_node_metadata

    update_node_metadata("node_001", {"firmware_name": "environment-node"})
    save_measurements("node_001", {"rssi": -55, "uptime_seconds": 321})
    response = client.get("/api/nodes/node_001")
    assert response.status_code == 200
    details = response.get_json()
    assert details["firmware_name"] == "environment-node"
    assert details["firmware_version"] is None
    assert details["rssi"] == -55
    assert details["uptime_seconds"] == 321
    assert details["status"] == "online"
    assert details["last_seen"] is not None


def test_node_details_unknown_metadata_and_missing_node(client):
    save_measurements("legacy_node", {"temperature": 20})
    details = client.get("/api/nodes/legacy_node").get_json()
    assert details["hardware_model"] is None
    assert details["ota_hostname"] is None
    assert client.get("/api/nodes/missing").status_code == 404
    assert client.get("/nodes/missing").status_code == 404


def test_node_details_page_and_clickable_dashboard_status(client):
    save_measurements("node_001", {"temperature": 20})
    page = client.get("/nodes/node_001")
    assert page.status_code == 200
    assert b"Node details" in page.data
    assert b"Firmware" in page.data
    script = client.get("/static/script.js")
    assert b"card-link" in script.data
    assert b"/nodes/" in script.data


def test_init_db_migrates_original_nodes_schema(tmp_path, monkeypatch):
    from app import database

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                location TEXT,
                node_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO nodes (node_id, name, node_type, created_at) VALUES (?, ?, ?, ?)",
            ("legacy", "Legacy", "esp32_wifi", "2025-01-01 00:00:00"),
        )
    monkeypatch.setattr(database, "DB_NAME", str(path))
    database.init_db()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(nodes)")}
        name = connection.execute("SELECT name FROM nodes WHERE node_id='legacy'").fetchone()[0]
    assert {"hardware_model", "hardware_revision", "firmware_name", "firmware_version", "ota_hostname"} <= columns
    assert name == "Legacy"
