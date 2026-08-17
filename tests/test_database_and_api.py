import sqlite3
from datetime import datetime, timedelta
from importlib import import_module

import pytest

from app.config import READING_LIMIT
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
        migrated = connection.execute(
            "SELECT name, enabled FROM nodes WHERE node_id='legacy'"
        ).fetchone()
    assert {
        "hardware_model", "hardware_revision", "firmware_name", "firmware_version",
        "ota_hostname", "category", "latitude", "longitude", "enabled",
    } <= columns
    assert migrated == ("Legacy", 1)


def test_registry_patch_updates_and_clears_user_fields(client):
    save_measurements("node_001", {"temperature": 20})
    response = client.patch("/api/nodes/node_001", json={
        "name": "  Greenhouse North  ", "location": "Bench 2", "category": "Climate",
        "latitude": 51.5, "longitude": -0.12, "enabled": False,
    })
    assert response.status_code == 200
    node = response.get_json()
    assert (node["name"], node["location"], node["category"]) == (
        "Greenhouse North", "Bench 2", "Climate",
    )
    assert (node["latitude"], node["longitude"]) == (51.5, -0.12)
    assert node["enabled"] is False
    assert node["status"] == "disabled"

    cleared = client.patch("/api/nodes/node_001", json={
        "location": " ", "category": None, "latitude": None, "longitude": None,
    }).get_json()
    assert cleared["location"] is None
    assert cleared["category"] is None
    assert cleared["latitude"] is None
    assert cleared["longitude"] is None


@pytest.mark.parametrize("payload", [
    {"name": ""}, {"name": None}, {"enabled": 1}, {"enabled": "true"},
    {"latitude": True}, {"latitude": 90.01}, {"latitude": float("nan")},
    {"longitude": -180.01}, {"longitude": float("inf")},
])
def test_registry_patch_rejects_invalid_values(client, payload):
    save_measurements("node_001", {"temperature": 20})
    assert client.patch("/api/nodes/node_001", json=payload).status_code == 400


@pytest.mark.parametrize("field", [
    "node_id", "node_type", "hardware_model", "firmware_version", "ota_hostname",
])
def test_registry_patch_rejects_immutable_and_device_fields(client, field):
    save_measurements("node_001", {"temperature": 20})
    assert client.patch("/api/nodes/node_001", json={field: "changed"}).status_code == 400
    assert client.get("/api/nodes/node_001").get_json()["node_id"] == "node_001"


def test_registry_patch_requires_existing_node(client):
    assert client.patch("/api/nodes/missing", json={"name": "Missing"}).status_code == 404


def test_enabled_status_semantics_and_disabled_http_ingestion(client):
    from app.database import get_node_status

    save_measurements("disabled_node", {"temperature": 20})
    client.patch("/api/nodes/disabled_node", json={"enabled": False})
    response = client.post("/api/data", json={
        "node_id": "disabled_node", "readings": {"humidity": 55},
    })
    assert response.status_code == 200
    assert get_node_status("disabled_node")["status"] == "disabled"
    assert client.get("/api/readings?node_id=disabled_node").get_json()[-1]["humidity"] == 55


def test_status_online_offline_and_unknown(isolated_database):
    from app.database import get_node_status, get_or_create_node

    with sqlite3.connect(isolated_database) as connection:
        get_or_create_node(connection.cursor(), "unknown_node")
        connection.commit()
    assert get_node_status("unknown_node")["status"] == "unknown"

    save_measurements("online_node", {"temperature": 20})
    assert get_node_status("online_node")["status"] == "online"

    save_measurements("offline_node", {"temperature": 20})
    stale = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(isolated_database) as connection:
        connection.execute(
            "UPDATE measurements SET timestamp = ? WHERE node_id = 'offline_node'", (stale,)
        )
    assert get_node_status("offline_node")["status"] == "offline"


def test_recent_readings_returns_complete_dynamic_cycles(isolated_database):
    from app.database import get_recent_measurements

    sensors = [
        "temperature", "humidity", "rssi", "uptime_seconds", "outside_temperature",
        "outside_humidity", "outside_pressure", "enclosure_temperature",
    ]
    cycle_count = READING_LIMIT + 6
    with sqlite3.connect(isolated_database) as connection:
        connection.execute(
            "INSERT INTO nodes (node_id, name, node_type, created_at) VALUES (?, ?, ?, ?)",
            ("busy_node", "Busy Node", "esp32_wifi", "2026-01-01 00:00:00"),
        )
        node_db_id = connection.execute(
            "SELECT id FROM nodes WHERE node_id = 'busy_node'"
        ).fetchone()[0]
        for cycle in range(cycle_count):
            timestamp = f"2026-01-01 00:{cycle:02d}:00"
            for offset, sensor in enumerate(sensors):
                connection.execute(
                    """INSERT INTO measurements
                       (node_db_id, node_id, sensor_type, value, unit, timestamp)
                       VALUES (?, 'busy_node', ?, ?, '', ?)""",
                    (node_db_id, sensor, cycle * 100 + offset, timestamp),
                )

    readings = get_recent_measurements("busy_node")
    assert len(readings) == READING_LIMIT
    assert [row["timestamp"] for row in readings] == sorted(row["timestamp"] for row in readings)
    assert readings[0]["timestamp"] == "2026-01-01 00:06:00"
    for cycle, reading in enumerate(readings, start=6):
        assert reading["node_id"] == "busy_node"
        assert set(reading) == {"timestamp", "node_id", *sensors}
        assert all(reading[sensor] == cycle * 100 + offset for offset, sensor in enumerate(sensors))


def test_recent_readings_query_index_is_present_and_used(isolated_database):
    with sqlite3.connect(isolated_database) as connection:
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(measurements)")}
        plan = connection.execute("""
            EXPLAIN QUERY PLAN
            SELECT timestamp FROM measurements
            WHERE node_id = ? ORDER BY timestamp DESC, id DESC
        """, ("node",)).fetchall()
    assert "idx_measurements_node_timestamp_id" in indexes
    assert any("idx_measurements_node_timestamp_id" in row[3] for row in plan)


def test_frontend_registry_and_selector_contract(client):
    script = client.get("/static/script.js").get_data(as_text=True)
    details_script = client.get("/static/node_details.js").get_data(as_text=True)
    page = client.get("/nodes/missing").get_data(as_text=True)
    assert "option.value = node.node_id" in script
    assert 'node.name.trim()' in script
    assert "nodeName || node.node_id" in script
    assert "encodeURIComponent(selectedNodeId)" in script
    assert 'id="editNode" class="button-primary" type="button" disabled' in page
    assert "editButton.disabled = false" in details_script
    assert "if (!currentNode) return;" in details_script
    assert 'id="headerStatus"' not in page
    assert 'id="statusDetails"' in page
    assert 'id="nodeInformationPanel"' in page
    assert 'id="editNode" class="button-primary"' in page
    panel_start = page.index('id="nodeInformationPanel"')
    node_information = page.index('id="nodeInformation"', panel_start)
    edit_control = page.index('id="editNode"', node_information)
    panel_end = page.index("</div>", edit_control)
    assert panel_start < node_information < edit_control < panel_end
    assert 'id="saveNode"' in page and 'id="cancelEdit"' in page
    assert 'document.getElementById("nodeInformation").innerHTML' in details_script
    assert "editButton.hidden = true" in details_script
    assert "saveButton.hidden = false" in details_script
    assert "cancelButton.hidden = false" in details_script
    assert 'document.getElementById("headerStatus")' not in details_script

CAPABILITY_KEYS = {
    "temperature_measurement", "humidity_measurement", "pressure_measurement",
    "soil_moisture_measurement", "soil_temperature_measurement", "relay_control",
    "pump_control", "valve_control", "wifi", "lorawan",
}


def test_capability_migration_seed_is_idempotent_and_preserves_nodes(isolated_database):
    from app import database
    database.save_measurements("legacy", {"temperature": 20})
    database.init_db()
    database.init_db()
    with sqlite3.connect(isolated_database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        rows = connection.execute(
            "SELECT capability_key, capability_class FROM capabilities"
        ).fetchall()
        assert connection.execute("SELECT name FROM nodes WHERE node_id='legacy'").fetchone()
    assert {"capabilities", "node_expected_capabilities", "node_reported_capabilities", "node_capability_reports"} <= tables
    assert len(rows) == len(CAPABILITY_KEYS) == len({row[0] for row in rows})
    assert {row[0] for row in rows} == CAPABILITY_KEYS
    classes = dict(rows)
    assert classes["temperature_measurement"] == "sensor"
    assert classes["relay_control"] == "actuator"
    assert classes["wifi"] == "communication"
    assert not {"i2c", "spi", "uart", "gpio"} & set(classes)


def test_capability_registry_api(client):
    response = client.get("/api/capabilities")
    assert response.status_code == 200
    definitions = response.get_json()
    assert {item["capability_key"] for item in definitions} == CAPABILITY_KEYS
    assert all(set(item) == {"capability_key", "display_name", "capability_class", "description"} for item in definitions)


def test_expected_capabilities_replace_deduplicate_empty_and_validate(client):
    from app.database import replace_reported_capabilities, save_measurements
    save_measurements("node", {"temperature": 20})
    replace_reported_capabilities("node", ["temperature_measurement", "wifi"])
    response = client.put("/api/nodes/node/capabilities", json={
        "expected": ["temperature_measurement", "temperature_measurement", "humidity_measurement"]
    })
    assert response.status_code == 200
    comparison = response.get_json()
    assert [item["capability_key"] for item in comparison["expected"]] == ["humidity_measurement", "temperature_measurement"]
    assert [item["capability_key"] for item in comparison["reported"]] == ["temperature_measurement", "wifi"]
    assert comparison["state"] == "capability_mismatch"
    assert [item["capability_key"] for item in comparison["missing"]] == ["humidity_measurement"]
    assert [item["capability_key"] for item in comparison["unexpected"]] == ["wifi"]
    assert client.put("/api/nodes/node/capabilities", json={"expected": []}).get_json()["state"] == "healthy"
    assert client.put("/api/nodes/node/capabilities", json={"expected": ["unknown"]}).status_code == 400
    assert client.put("/api/nodes/missing/capabilities", json={"expected": []}).status_code == 404


@pytest.mark.parametrize("payload", [None, {}, {"expected": "wifi"}, {"expected": [1]}, {"expected": [], "extra": 1}])
def test_expected_capability_api_validation(client, payload):
    save_measurements("node", {"temperature": 20})
    assert client.put("/api/nodes/node/capabilities", json=payload).status_code == 400


def test_capability_comparison_and_health_precedence(client, isolated_database):
    from app.database import replace_reported_capabilities
    save_measurements("node", {"temperature": 20})
    unknown = client.get("/api/nodes/node").get_json()
    assert unknown["capabilities"]["state"] == "unknown"
    assert unknown["health"] == "unknown"
    client.put("/api/nodes/node/capabilities", json={"expected": ["temperature_measurement", "humidity_measurement"]})
    replace_reported_capabilities("node", ["temperature_measurement", "wifi"])
    mismatch = client.get("/api/nodes/node").get_json()
    assert mismatch["health"] == "capability_mismatch"
    client.put("/api/nodes/node/capabilities", json={"expected": ["temperature_measurement"]})
    healthy = client.get("/api/nodes/node").get_json()
    assert healthy["health"] == "healthy"
    assert [item["capability_key"] for item in healthy["capabilities"]["unexpected"]] == ["wifi"]
    client.patch("/api/nodes/node", json={"enabled": False})
    assert client.get("/api/nodes/node").get_json()["health"] == "disabled"


def test_empty_reported_set_is_known_and_can_mismatch(client):
    from app.database import replace_reported_capabilities
    save_measurements("node", {"temperature": 20})
    client.put("/api/nodes/node/capabilities", json={"expected": ["wifi"]})
    replace_reported_capabilities("node", [])
    details = client.get("/api/nodes/node").get_json()
    assert details["capabilities"]["reported_at"] is not None
    assert details["capabilities"]["state"] == "capability_mismatch"


def test_capability_ui_contract(client):
    page = client.get("/nodes/missing").get_data(as_text=True)
    script = client.get("/static/node_details.js").get_data(as_text=True)
    for target in ["capabilityDetails", "capabilityEditor", "editCapabilities", "saveCapabilities", "cancelCapabilities"]:
        assert f'id="{target}"' in page
    assert "Sensors" in script and "Actuators" in script and "Communication" in script
    assert 'name="expectedCapability"' in script
    assert "/capabilities`" in script
    assert page.index('id="nodeInformationPanel"') < page.index('id="capabilitiesPanel"')


def test_fleet_page_and_dashboard_navigation(client):
    fleet_page = client.get("/nodes")
    assert fleet_page.status_code == 200
    assert b"All Nodes" in fleet_page.data
    assert b"Fleet registry and node navigation" in fleet_page.data
    assert b"/static/nodes.js" in fleet_page.data
    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert b'href="/nodes">All Nodes</a>' in dashboard.data


def test_fleet_overview_runtime_and_health_semantics(client, isolated_database):
    from app.database import get_or_create_node, replace_reported_capabilities

    for node_id in ("unknown", "disabled"):
        with sqlite3.connect(isolated_database) as connection:
            get_or_create_node(connection.cursor(), node_id, name=node_id.title())
            connection.commit()
    save_measurements("online", {"temperature": 20})
    save_measurements("offline", {"temperature": 20})
    save_measurements("mismatch", {"temperature": 20})
    client.patch("/api/nodes/online", json={"name": "Weather Station"})
    client.patch("/api/nodes/disabled", json={"enabled": False})
    client.put("/api/nodes/online/capabilities", json={"expected": []})
    replace_reported_capabilities("online", [])
    client.put("/api/nodes/mismatch/capabilities", json={"expected": ["wifi"]})
    replace_reported_capabilities("mismatch", [])
    stale = (datetime.now() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(isolated_database) as connection:
        connection.execute(
            "UPDATE measurements SET timestamp = ? WHERE node_id = 'offline'", (stale,)
        )

    response = client.get("/api/nodes/overview")
    assert response.status_code == 200
    nodes = {node["node_id"]: node for node in response.get_json()}
    assert nodes["online"] == {
        "node_id": "online", "name": "Weather Station",
        "status": "online", "health": "healthy",
    }
    assert (nodes["offline"]["status"], nodes["offline"]["health"]) == ("offline", "offline")
    assert (nodes["disabled"]["status"], nodes["disabled"]["health"]) == ("disabled", "disabled")
    assert (nodes["unknown"]["status"], nodes["unknown"]["health"]) == ("unknown", "unknown")
    assert (nodes["mismatch"]["status"], nodes["mismatch"]["health"]) == (
        "online", "capability_mismatch",
    )

    # The dedicated overview does not enlarge or rename the existing registry API.
    registry = {node["node_id"]: node for node in client.get("/api/nodes").get_json()}
    assert "status" not in registry["online"] and "health" not in registry["online"]
    assert client.get("/nodes/online").status_code == 200


def test_fleet_latest_state_query_is_index_backed_and_history_bounded(isolated_database):
    from app.database import get_nodes_overview, get_or_create_node

    with sqlite3.connect(isolated_database) as connection:
        node_db_id = get_or_create_node(connection.cursor(), "history", name="History")
        for item in range(2000):
            connection.execute(
                """INSERT INTO measurements
                   (node_db_id, node_id, sensor_type, value, unit, timestamp)
                   VALUES (?, 'history', 'temperature', ?, '°C', ?)""",
                (node_db_id, item, f"2020-01-01 00:{item % 60:02d}:00"),
            )
        latest = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        connection.execute(
            """INSERT INTO measurements
               (node_db_id, node_id, sensor_type, value, unit, timestamp)
               VALUES (?, 'history', 'temperature', 20, '°C', ?)""",
            (node_db_id, latest),
        )
        plan = connection.execute("""
            EXPLAIN QUERY PLAN
            SELECT n.node_id,
                   (SELECT m.timestamp FROM measurements AS m
                    WHERE m.node_id = n.node_id
                    ORDER BY m.timestamp DESC, m.id DESC LIMIT 1)
            FROM nodes AS n
        """).fetchall()
    assert get_nodes_overview()[0]["status"] == "online"
    assert any(
        "idx_measurements_node_timestamp_id" in row[3] and "SEARCH m" in row[3]
        for row in plan
    )


def test_dashboard_query_parameter_and_fleet_javascript_contract(client):
    dashboard_script = client.get("/static/script.js").get_data(as_text=True)
    fleet_script = client.get("/static/nodes.js").get_data(as_text=True)
    assert 'new URLSearchParams(window.location.search).get("node_id")' in dashboard_script
    assert "nodes.some(node => node.node_id === requestedNodeId)" in dashboard_script
    assert "const selectedNodeIds = new Set()" in fleet_script
    assert "visibleNodes()" in fleet_script
    assert "encodeURIComponent(node.node_id)" in fleet_script
    assert "selectedNodeIds.clear()" in fleet_script
    assert "FLEET_REFRESH_INTERVAL_MS = 10000" in fleet_script
