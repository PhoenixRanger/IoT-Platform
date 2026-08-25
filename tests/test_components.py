import re
import sqlite3

import pytest

from app.database import get_node_capabilities, save_measurements


def definition(definition_key="test-multi-sensor", component_class="sensor", interfaces=None,
               capabilities=None):
    return {"definition_key": definition_key, "display_name": "Test Multi Sensor",
            "manufacturer": "Example", "model": "T1", "component_class": component_class,
            "interfaces": ["i2c", "uart"] if interfaces is None else interfaces,
            "capabilities": (["temperature_measurement", "humidity_measurement"]
                             if capabilities is None else capabilities)}


def create_node(client, node_id="node-a"):
    save_measurements(node_id, {"temperature": 20})


def test_component_seeds_and_schema_are_idempotent(isolated_database):
    from app.database import COMPONENT_SEEDS, init_db
    init_db(); init_db()
    with sqlite3.connect(isolated_database) as connection:
        ids = {row[0] for row in connection.execute("SELECT definition_key FROM component_definitions")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert ids == {seed["definition_key"] for seed in COMPONENT_SEEDS}
    assert {"component_definitions", "component_interface_requirements", "component_capabilities",
            "connected_components", "component_capability_instances"} <= tables
    assert {"idx_connected_components_node_active", "idx_connected_components_definition",
            "idx_component_capabilities_definition", "idx_component_definitions_lifecycle",
            "idx_active_capability_instance", "idx_capability_instances_component",
            "idx_capability_instances_capability"} <= indexes
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM component_capability_instances"
        ).fetchone()[0] == 0
    with sqlite3.connect(isolated_database) as connection:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(component_definitions)"
        )}
    assert {"lifecycle_status", "removed_at"} <= columns


def test_definition_lifecycle_migrates_existing_v115_table(tmp_path, monkeypatch):
    from app import database

    path = tmp_path / "v115_components.db"
    with sqlite3.connect(path) as connection:
        connection.execute("""
            CREATE TABLE component_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                component_id TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                manufacturer TEXT,
                model TEXT,
                component_class TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        connection.execute("""INSERT INTO component_definitions
            (component_id, display_name, component_class, created_at, updated_at)
            VALUES ('existing-sensor', 'Existing Sensor', 'sensor',
                    '2026-01-01 00:00:00', '2026-01-01 00:00:00')""")
    monkeypatch.setattr(database, "DB_NAME", str(path))
    database.init_db()
    database.init_db()
    with sqlite3.connect(path) as connection:
        columns = {row[1] for row in connection.execute(
            "PRAGMA table_info(component_definitions)"
        )}
        lifecycle = connection.execute("""SELECT lifecycle_status, removed_at
            FROM component_definitions WHERE definition_key = 'existing-sensor'""").fetchone()
    assert {"lifecycle_status", "removed_at"} <= columns
    assert lifecycle == ("active", None)


def test_pr33_connected_component_schema_migration_preserves_child_ids(tmp_path, monkeypatch, client):
    from app import database

    path = tmp_path / "pr33.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT, node_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL, location TEXT, node_type TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE capabilities (
                id INTEGER PRIMARY KEY AUTOINCREMENT, capability_key TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, capability_class TEXT NOT NULL, description TEXT NOT NULL
            );
            CREATE TABLE component_definitions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, component_id TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL, manufacturer TEXT, model TEXT,
                component_class TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                lifecycle_status TEXT NOT NULL DEFAULT 'active', removed_at TEXT
            );
            CREATE TABLE component_capabilities (
                component_definition_id INTEGER NOT NULL, capability_id INTEGER NOT NULL,
                PRIMARY KEY (component_definition_id, capability_id)
            );
            CREATE TABLE node_component_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT, instance_id TEXT NOT NULL UNIQUE,
                node_db_id INTEGER NOT NULL, component_definition_id INTEGER NOT NULL,
                label TEXT NOT NULL, location TEXT, zone TEXT, lifecycle_status TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, removed_at TEXT
            );
            CREATE TABLE component_capability_instances (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                capability_instance_id TEXT NOT NULL UNIQUE,
                connected_component_id INTEGER NOT NULL, capability_id INTEGER NOT NULL,
                lifecycle_status TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, removed_at TEXT,
                FOREIGN KEY (connected_component_id) REFERENCES node_component_instances(id)
            );
            INSERT INTO nodes (node_id, name, node_type, created_at)
                VALUES ('legacy-node', 'Legacy Node', 'esp32_wifi', '2026-01-01 00:00:00');
            INSERT INTO capabilities
                (capability_key, display_name, capability_class, description)
                VALUES ('temperature_measurement', 'Temperature', 'sensor', 'Measures temperature.');
            INSERT INTO component_definitions
                (component_id, display_name, manufacturer, model, component_class, created_at, updated_at)
                VALUES ('legacy-definition', 'Legacy Definition', 'Example', 'One', 'sensor',
                        '2026-01-01 00:00:00', '2026-01-01 00:00:00');
            INSERT INTO component_capabilities VALUES (1, 1);
            INSERT INTO node_component_instances
                (instance_id, node_db_id, component_definition_id, label, lifecycle_status,
                 created_at, updated_at)
                VALUES ('ci_oldphysical1', 1, 1, 'Legacy Sensor', 'active',
                        '2026-01-01 00:00:00', '2026-01-01 00:00:00');
            INSERT INTO component_capability_instances
                (capability_instance_id, connected_component_id, capability_id,
                 lifecycle_status, created_at, updated_at)
                VALUES ('ci_existing_child', 1, 1, 'active',
                        '2026-01-01 00:00:00', '2026-01-01 00:00:00');
        """)
    monkeypatch.setattr(database, "DB_NAME", str(path))

    database.init_db()
    with sqlite3.connect(path) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )}
        parent = connection.execute("""SELECT connected_component_id, legacy_route_id
            FROM connected_components WHERE id = 1""").fetchone()
        first_children = [row[0] for row in connection.execute("""SELECT capability_instance_id
            FROM component_capability_instances WHERE connected_component_id = 1 ORDER BY id""")]
        parent_foreign_key = next(
            row[2] for row in connection.execute(
                "PRAGMA foreign_key_list(component_capability_instances)"
            ) if row[3] == "connected_component_id"
        )
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    assert "connected_components" in tables and "node_component_instances" not in tables
    assert re.fullmatch(r"nc_[0-9a-f]{10}", parent[0])
    assert parent[1] == "ci_oldphysical1"
    assert first_children == ["ci_existing_child"]
    assert parent_foreign_key == "connected_components"
    assert foreign_key_errors == []
    legacy_page = client.get("/nodes/legacy-node/components/ci_oldphysical1")
    assert legacy_page.status_code == 302
    assert legacy_page.headers["Location"].endswith(
        f"/nodes/legacy-node/components/{parent[0]}"
    )

    database.init_db()
    database.init_db()
    with sqlite3.connect(path) as connection:
        second_parent = connection.execute("""SELECT connected_component_id, legacy_route_id
            FROM connected_components WHERE id = 1""").fetchone()
        second_children = [row[0] for row in connection.execute("""SELECT capability_instance_id
            FROM component_capability_instances WHERE connected_component_id = 1 ORDER BY id""")]
    assert second_parent == parent
    assert second_children == first_children


def test_create_sensor_actuator_multiple_interfaces_and_shared_capability(client):
    sensor = client.post("/api/components", json=definition()).get_json()
    actuator_response = client.post("/api/components", json=definition(
        "test-switch", "actuator", ["digital_signal"], ["switched_output"]))
    other = client.post("/api/components", json=definition(
        "other-temp", "sensor", ["spi"], ["temperature_measurement"])).get_json()
    assert actuator_response.status_code == 201
    assert sensor["interfaces"] == ["i2c", "uart"]
    assert {item["capability_key"] for item in sensor["capabilities"]} == {
        "temperature_measurement", "humidity_measurement"}
    assert other["capabilities"][0]["capability_key"] == "temperature_measurement"


def test_custom_definition_generates_internal_key_without_user_id(client):
    payload = definition()
    payload.pop("definition_key")
    created = client.post("/api/components", json=payload)
    assert created.status_code == 201
    result = created.get_json()
    assert re.fullmatch(r"def_[0-9a-f]{10}", result["definition_key"])
    assert "component_id" not in result
    assert client.get(f'/api/components/{result["definition_key"]}').status_code == 200


def test_component_definition_validation_identity_and_duplicates(client):
    assert client.post("/api/components", json=definition()).status_code == 201
    assert client.post("/api/components", json=definition()).status_code == 400
    assert client.patch("/api/components/test-multi-sensor", json={"definition_key": "changed"}).status_code == 400
    assert client.post("/api/components", json=definition("Bad ID")).status_code == 400
    assert client.post("/api/components", json=definition("bad-class", "board")).status_code == 400
    assert client.post("/api/components", json=definition("bad-interface", interfaces=["gpio"])).status_code == 400
    assert client.post("/api/components", json=definition("unknown-cap", capabilities=["unknown"])).status_code == 400
    assert client.post("/api/components", json=definition("duplicate-interface", interfaces=["i2c", "i2c"])).status_code == 400
    assert client.post("/api/components", json=definition("duplicate-cap", capabilities=["wifi", "wifi"])).status_code == 400


def test_component_definition_requires_interfaces_and_capabilities(client):
    no_interfaces = client.post(
        "/api/components", json=definition("no-interfaces", interfaces=[])
    )
    no_capabilities = client.post(
        "/api/components", json=definition("no-capabilities", capabilities=[])
    )
    assert no_interfaces.status_code == 400
    assert "at least one interface" in no_interfaces.get_json()["error"]
    assert no_capabilities.status_code == 400
    assert "at least one capability" in no_capabilities.get_json()["error"]

    client.post("/api/components", json=definition())
    assert client.patch(
        "/api/components/test-multi-sensor", json={"interfaces": []}
    ).status_code == 400
    assert client.patch(
        "/api/components/test-multi-sensor", json={"capabilities": []}
    ).status_code == 400
    unchanged = client.get("/api/components/test-multi-sensor").get_json()
    assert unchanged["interfaces"] == ["i2c", "uart"]
    assert len(unchanged["capabilities"]) == 2


def test_component_definitions_reject_communication_capabilities(client):
    from app.database import get_capabilities, replace_reported_capabilities

    for definition_key, capability in (("wifi-component", "wifi"),
                                     ("lorawan-component", "lorawan")):
        response = client.post(
            "/api/components", json=definition(definition_key, capabilities=[capability])
        )
        assert response.status_code == 400
        assert "Communication capabilities" in response.get_json()["error"]

    client.post("/api/components", json=definition())
    for capability in ("wifi", "lorawan"):
        response = client.patch(
            "/api/components/test-multi-sensor", json={"capabilities": [capability]}
        )
        assert response.status_code == 400
    assert {item["capability_key"] for item in get_capabilities()} >= {"wifi", "lorawan"}

    create_node(client)
    replace_reported_capabilities("node-a", ["wifi"])
    assert [item["capability_key"] for item in get_node_capabilities("node-a")["reported"]] == ["wifi"]


def test_definition_update_and_safe_delete(client):
    client.post("/api/components", json=definition())
    updated = client.patch("/api/components/test-multi-sensor", json={
        "display_name": "Updated", "manufacturer": None, "model": "T2",
        "component_class": "sensor", "interfaces": ["analog_signal"],
        "capabilities": ["temperature_measurement"]})
    assert updated.status_code == 200
    assert updated.get_json()["interfaces"] == ["analog_signal"]
    assert client.delete("/api/components/test-multi-sensor").status_code == 200
    assert client.get("/api/components/test-multi-sensor").status_code == 404


def test_definition_archive_requires_zero_active_assignments_and_preserves_history(client):
    client.post("/api/components", json=definition())
    create_node(client)
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "test-multi-sensor", "label": "Outside Sensor"
    }).get_json()

    blocked = client.delete("/api/components/test-multi-sensor")
    assert blocked.status_code == 409
    assert "currently assigned" in blocked.get_json()["error"]

    component_url = f'/api/nodes/node-a/components/{component["connected_component_id"]}'
    assert client.delete(component_url).status_code == 200
    removed = client.delete("/api/components/test-multi-sensor")
    assert removed.status_code == 200
    assert removed.get_json()["status"] == "removed"
    assert "test-multi-sensor" not in {
        item["definition_key"] for item in client.get("/api/components").get_json()
    }

    archived = {item["definition_key"]: item for item in client.get(
        "/api/components?include_removed=true"
    ).get_json()}["test-multi-sensor"]
    assert archived["lifecycle_status"] == "removed"
    assert archived["active_connected_component_count"] == 0
    assert archived["historical_connected_component_count"] == 1
    historical = client.get("/api/nodes/node-a/components?include_removed=true").get_json()
    assert historical[0]["connected_component_id"] == component["connected_component_id"]
    assert historical[0]["definition_key"] == "test-multi-sensor"
    historical_detail = client.get(component_url).get_json()
    assert historical_detail["connected_component_id"] == component["connected_component_id"]
    assert historical_detail["display_name"] == "Test Multi Sensor"
    assert client.post("/api/nodes/node-a/components", json={
        "definition_key": "test-multi-sensor", "label": "Cannot Add"
    }).status_code == 404
    recreated = client.post("/api/components", json=definition())
    assert recreated.status_code == 400
    assert "definition_key already exists" in recreated.get_json()["error"]


def test_archived_seed_definition_is_not_resurrected(isolated_database):
    from app.database import delete_component_definition, init_db, list_component_definitions

    assert delete_component_definition("aosong-dht22") == "removed"
    init_db()
    init_db()
    active_ids = {item["definition_key"] for item in list_component_definitions()}
    historical = {item["definition_key"]: item for item in list_component_definitions(True)}
    assert "aosong-dht22" not in active_ids
    assert historical["aosong-dht22"]["lifecycle_status"] == "removed"


def test_instance_creation_identity_multiplicity_and_joined_metadata(client):
    client.post("/api/components", json=definition())
    create_node(client); create_node(client, "node-b")
    payload = {"definition_key": "test-multi-sensor", "label": "Outside", "location": "field", "zone": "north"}
    first = client.post("/api/nodes/node-a/components", json=payload)
    second = client.post("/api/nodes/node-a/components", json=payload)
    third = client.post("/api/nodes/node-b/components", json=payload)
    assert all(response.status_code == 201 for response in (first, second, third))
    ids = {response.get_json()["connected_component_id"] for response in (first, second, third)}
    assert len(ids) == 3 and all(re.fullmatch(r"nc_[0-9a-f]{10}", item) for item in ids)
    capability_ids = {
        capability["capability_instance_id"]
        for response in (first, second, third)
        for capability in response.get_json()["capability_instances"]
    }
    assert len(capability_ids) == 6
    assert all(re.fullmatch(r"ci_[0-9a-f]{10}", item) for item in capability_ids)
    assert len(client.get("/api/nodes/node-a/components").get_json()) == 2
    item = first.get_json()
    assert item["definition_key"] == "test-multi-sensor" and len(item["capabilities"]) == 2


def test_seeded_components_materialize_distinct_capability_instances(client):
    create_node(client)
    ms8607 = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Outside Sensor"
    }).get_json()
    dht22 = client.post("/api/nodes/node-a/components", json={
        "definition_key": "aosong-dht22", "label": "Enclosure Sensor"
    }).get_json()
    second_ms8607 = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Second Outside Sensor"
    }).get_json()

    assert {item["display_name"] for item in ms8607["capability_instances"]} == {
        "Temperature", "Humidity", "Pressure"
    }
    assert {item["display_name"] for item in dht22["capability_instances"]} == {
        "Temperature", "Humidity"
    }
    ms_ids = {
        item["capability_instance_id"]
        for component in (ms8607, second_ms8607)
        for item in component["capability_instances"]
    }
    assert len(ms_ids) == 6
    assert all(re.fullmatch(r"ci_[0-9a-f]{10}", item) for item in ms_ids)


def test_capability_instance_ids_survive_metadata_edits_and_reconciliation(client):
    from app.database import init_db

    create_node(client)
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Outside Sensor"
    }).get_json()
    url = f'/api/nodes/node-a/components/{component["connected_component_id"]}'
    original = {
        item["capability_key"]: item["capability_instance_id"]
        for item in component["capability_instances"]
    }
    connected_component_id = component["connected_component_id"]
    for payload in ({"label": "Weather Mast"}, {"location": "roof"}, {"zone": "west"}):
        response = client.patch(url, json=payload).get_json()
        assert {
            item["capability_key"]: item["capability_instance_id"]
            for item in response["capability_instances"]
        } == original
        assert response["connected_component_id"] == connected_component_id
    init_db()
    init_db()
    after_restart = client.get(url).get_json()
    assert {
        item["capability_key"]: item["capability_instance_id"]
        for item in after_restart["capability_instances"]
    } == original
    assert after_restart["connected_component_id"] == connected_component_id
    assert "component_id" not in after_restart
    assert after_restart["definition"]["definition_key"] == "te-ms8607"


def test_definition_capability_edits_reconcile_children_and_preserve_history(client):
    client.post("/api/components", json=definition(
        capabilities=["temperature_measurement"]
    ))
    create_node(client)
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "test-multi-sensor", "label": "Sensor"
    }).get_json()
    second_component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "test-multi-sensor", "label": "Second Sensor"
    }).get_json()
    url = f'/api/nodes/node-a/components/{component["connected_component_id"]}'
    second_url = f'/api/nodes/node-a/components/{second_component["connected_component_id"]}'
    original_temperature_id = component["capability_instances"][0]["capability_instance_id"]

    client.patch("/api/components/test-multi-sensor", json={
        "capabilities": ["temperature_measurement", "humidity_measurement"]
    })
    added = client.get(url).get_json()["capability_instances"]
    assert {item["capability_key"] for item in added} == {
        "temperature_measurement", "humidity_measurement"
    }
    assert {item["capability_key"] for item in client.get(second_url).get_json()[
        "capability_instances"]} == {"temperature_measurement", "humidity_measurement"}
    assert next(item for item in added if item["capability_key"] == "temperature_measurement")[
        "capability_instance_id"] == original_temperature_id

    client.patch("/api/components/test-multi-sensor", json={
        "capabilities": ["humidity_measurement"]
    })
    assert [item["capability_key"] for item in client.get(url).get_json()[
        "capability_instances"]] == ["humidity_measurement"]

    client.patch("/api/components/test-multi-sensor", json={
        "capabilities": ["temperature_measurement", "humidity_measurement"]
    })
    readded = client.get(url).get_json()["capability_instances"]
    new_temperature_id = next(
        item["capability_instance_id"] for item in readded
        if item["capability_key"] == "temperature_measurement"
    )
    assert new_temperature_id != original_temperature_id


def test_definition_reconciliation_failure_rolls_back(client, monkeypatch):
    from app import database

    client.post("/api/components", json=definition(
        capabilities=["temperature_measurement"]
    ))
    create_node(client)
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "test-multi-sensor", "label": "Sensor"
    }).get_json()
    original = component["capability_instances"]
    monkeypatch.setattr(
        database, "_new_capability_instance_id",
        lambda cursor: (_ for _ in ()).throw(RuntimeError("generation failed")),
    )
    with pytest.raises(RuntimeError, match="generation failed"):
        database.update_component_definition("test-multi-sensor", {
            "capabilities": ["temperature_measurement", "humidity_measurement"]
        })
    definition_state = database.get_component_definition("test-multi-sensor")
    assert [item["capability_key"] for item in definition_state["capabilities"]] == [
        "temperature_measurement"
    ]
    assert client.get(
        f'/api/nodes/node-a/components/{component["connected_component_id"]}'
    ).get_json()["capability_instances"] == original


def test_instance_creation_location_and_zone_are_optional(client):
    client.post("/api/components", json=definition())
    create_node(client)
    payloads = [
        {"definition_key": "test-multi-sensor", "label": "Sensor"},
        {"definition_key": "test-multi-sensor", "label": "Sensor", "location": None},
        {"definition_key": "test-multi-sensor", "label": "Sensor", "zone": "zone-1"},
    ]
    created = [client.post("/api/nodes/node-a/components", json=item) for item in payloads]
    assert all(response.status_code == 201 for response in created)
    results = [response.get_json() for response in created]
    assert (results[0]["location"], results[0]["zone"]) == (None, None)
    assert (results[1]["location"], results[1]["zone"]) == (None, None)
    assert (results[2]["location"], results[2]["zone"]) == (None, "zone-1")


def test_instance_validation_edit_immutability_and_lifecycle(client):
    client.post("/api/components", json=definition()); create_node(client)
    assert client.post("/api/nodes/missing/components", json={"definition_key":"test-multi-sensor","label":"x","location":None,"zone":None}).status_code == 404
    assert client.post("/api/nodes/node-a/components", json={"definition_key":"missing","label":"x","location":None,"zone":None}).status_code == 404
    item = client.post("/api/nodes/node-a/components", json={"definition_key":"test-multi-sensor","label":"Old","location":None,"zone":None}).get_json()
    url = f'/api/nodes/node-a/components/{item["connected_component_id"]}'
    assert client.patch(url, json={"definition_key": "aosong-dht22"}).status_code == 400
    edited = client.patch(url, json={"label":"New","location":"outside","zone":"z1"}).get_json()
    assert (edited["label"], edited["location"], edited["zone"]) == ("New", "outside", "z1")
    assert client.delete(url).status_code == 200
    assert client.get("/api/nodes/node-a/components").get_json() == []
    historical = client.get("/api/nodes/node-a/components?include_removed=true").get_json()
    assert historical[0]["lifecycle_status"] == "removed" and historical[0]["removed_at"]
    assert client.patch(url, json={"label":"Again"}).status_code == 400
    assert client.delete(url).status_code == 409
    assert client.get("/api/components/test-multi-sensor").status_code == 200
    assert client.delete("/api/components/test-multi-sensor").status_code == 200
    assert client.get("/api/components/test-multi-sensor").status_code == 404
    historical = client.get("/api/nodes/node-a/components?include_removed=true").get_json()
    assert historical[0]["definition_key"] == "test-multi-sensor"


def test_expected_counts_derive_from_active_components_and_reporting_stays_separate(client):
    from app.database import replace_reported_capabilities
    client.post("/api/components", json=definition()); create_node(client)
    payload={"definition_key":"test-multi-sensor","label":"Sensor","location":None,"zone":None}
    first=client.post("/api/nodes/node-a/components",json=payload).get_json()
    client.post("/api/nodes/node-a/components",json=payload)
    replace_reported_capabilities("node-a", ["temperature_measurement", "wifi"])
    state=get_node_capabilities("node-a")
    counts={item["capability_key"]:item["count"] for item in state["expected"]}
    assert counts == {"humidity_measurement":2, "temperature_measurement":2}
    assert "wifi" not in counts
    assert {item["capability_key"] for item in state["reported"]} == {"temperature_measurement", "wifi"}
    assert [item["capability_key"] for item in state["missing"]] == ["humidity_measurement"]
    client.delete(f'/api/nodes/node-a/components/{first["connected_component_id"]}')
    assert {item["capability_key"]:item["count"] for item in get_node_capabilities("node-a")["expected"]} == {
        "humidity_measurement":1,"temperature_measurement":1}


def test_expected_counts_follow_active_capability_instances(client):
    create_node(client)
    ms8607 = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Outside"
    }).get_json()
    dht22 = client.post("/api/nodes/node-a/components", json={
        "definition_key": "aosong-dht22", "label": "Enclosure"
    }).get_json()
    assert {item["capability_key"]: item["count"] for item in
            get_node_capabilities("node-a")["expected"]} == {
        "temperature_measurement": 2,
        "humidity_measurement": 2,
        "pressure_measurement": 1,
    }
    client.delete(f'/api/nodes/node-a/components/{dht22["connected_component_id"]}')
    assert {item["capability_key"]: item["count"] for item in
            get_node_capabilities("node-a")["expected"]} == {
        "temperature_measurement": 1,
        "humidity_measurement": 1,
        "pressure_measurement": 1,
    }
    client.delete(f'/api/nodes/node-a/components/{ms8607["connected_component_id"]}')
    assert get_node_capabilities("node-a")["expected"] == []


def test_legacy_expected_rows_do_not_affect_current_state_or_fleet(client):
    from app.database import get_nodes_overview, replace_expected_capabilities
    from app.database import replace_reported_capabilities

    create_node(client)
    replace_expected_capabilities("node-a", ["wifi", "temperature_measurement"])
    replace_reported_capabilities("node-a", ["wifi"])

    state = get_node_capabilities("node-a")
    assert state["expected"] == []
    assert state["missing"] == []
    assert [item["capability_key"] for item in state["reported"]] == ["wifi"]
    assert [item["capability_key"] for item in state["unexpected"]] == ["wifi"]
    assert state["state"] == "healthy"

    overview = get_nodes_overview()[0]
    assert overview["expected_capabilities"] == []
    assert overview["health"] == "healthy"


def test_removing_one_instance_does_not_affect_other_or_telemetry(client):
    client.post("/api/components", json=definition()); create_node(client)
    payload={"definition_key":"test-multi-sensor","label":"Sensor","location":None,"zone":None}
    first=client.post("/api/nodes/node-a/components",json=payload).get_json()
    second=client.post("/api/nodes/node-a/components",json=payload).get_json()
    client.delete(f'/api/nodes/node-a/components/{first["connected_component_id"]}')
    assert [item["connected_component_id"] for item in client.get("/api/nodes/node-a/components").get_json()] == [second["connected_component_id"]]
    response=client.post("/api/data",json={"node_id":"node-a","readings":{"humidity":55}})
    assert response.status_code == 200 and response.get_json()["saved"][0]["value"] == 55


def test_connected_component_removal_cascades_capability_lifecycle(client):
    create_node(client)
    first = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "First"
    }).get_json()
    second = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Second"
    }).get_json()
    first_ids = {
        item["capability_instance_id"] for item in first["capability_instances"]
    }
    second_ids = {
        item["capability_instance_id"] for item in second["capability_instances"]
    }
    client.delete(f'/api/nodes/node-a/components/{first["connected_component_id"]}')
    historical = client.get(
        f'/api/nodes/node-a/components/{first["connected_component_id"]}'
    ).get_json()
    assert historical["lifecycle_status"] == "removed"
    assert {item["capability_instance_id"] for item in
            historical["capability_instances"]} == first_ids
    assert all(item["lifecycle_status"] == "removed"
               for item in historical["capability_instances"])
    active_second = client.get(
        f'/api/nodes/node-a/components/{second["connected_component_id"]}'
    ).get_json()
    assert {item["capability_instance_id"] for item in
            active_second["capability_instances"]} == second_ids
    assert all(item["lifecycle_status"] == "active"
               for item in active_second["capability_instances"])


def test_component_pages_and_navigation_contract(client):
    create_node(client)
    library=client.get("/components").get_data(as_text=True)
    fleet=client.get("/nodes").get_data(as_text=True)
    technical=client.get("/nodes/node-a/technical").get_data(as_text=True)
    assert "Component Library" in library and "+ Create Component" in library
    assert fleet.index('href="/components"') < fleet.index('href="/fleet/organization"') < fleet.index('href="/"')
    assert "+ Add Component" in technical and "nodeComponentRows" in technical and "removeDialog" in technical
    item=client.post("/api/nodes/node-a/components",json={"definition_key":"te-ms8607","label":"Outside","location":"outside","zone":None}).get_json()
    page=client.get(f'/nodes/node-a/components/{item["connected_component_id"]}')
    assert page.status_code == 200 and b"Provided Capabilities" in page.data


def test_component_library_and_node_component_menu_contract(client):
    create_node(client)
    library = client.get("/components").get_data(as_text=True)
    library_script = client.get("/static/components.js").get_data(as_text=True)
    technical = client.get("/nodes/node-a/technical").get_data(as_text=True)
    technical_script = client.get("/static/node_technical.js").get_data(as_text=True)
    styles = client.get("/static/style.css").get_data(as_text=True)

    for column in ("Name", "Class", "Manufacturer / Model",
                   "Interface(s)", "Capabilities"):
        assert f"<th>{column}</th>" in library
    assert "<th>Component ID</th>" not in library
    assert 'id="componentId"' not in library
    assert "Component ID is immutable" not in library
    assert '<span class="visually-hidden">Actions</span>' in library
    assert "compact-actions" not in library_script
    assert 'trigger.textContent = "⋮"' in library_script
    assert '[["Edit", () => openForm(item)], ["Delete", () => deleteDefinition(item)]]' in library_script
    assert 'capability.capability_class !== "communication"' in library_script
    assert "aria-expanded" in library_script and 'event.key === "Escape"' in library_script

    assert "component-table-wrapper" in library and "component-table-wrapper" in technical
    assert "<th>Label</th>" in technical
    assert "Label / Instance ID" not in technical
    assert 'textContent=item.connected_component_id' not in technical_script
    assert 'button.textContent="⋮"' in technical_script
    for action in ("View Details / Open", "Edit", "Remove"):
        assert action in technical_script
    assert "menu-open" in technical_script and "aria-expanded" in technical_script
    assert ".component-table-wrapper { overflow:visible; }" in styles
    assert ".component-table tr.menu-open { position:relative; z-index:10; }" in styles


def test_component_detail_cleanup_and_edit_contract(client):
    create_node(client)
    item = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Outside Sensor"
    }).get_json()
    page = client.get(
        f'/nodes/node-a/components/{item["connected_component_id"]}'
    ).get_data(as_text=True)
    script = client.get("/static/component_detail.js").get_data(as_text=True)
    styles = client.get("/static/style.css").get_data(as_text=True)

    assert "Node Details" in page
    assert "Component Details" in page
    assert "Interfaces" in page
    assert "Physical Instance" not in page
    assert "Reusable Definition" not in page
    assert "node component ID" not in page
    assert "Provided Capabilities" in page and "Read-only in v1.15.0" in page
    assert 'id="editComponent"' in page and "Edit Component" in page
    assert 'id="editComponentDialog"' in page
    assert 'row("Removed"' not in script and 'row("Lifecycle"' not in script
    for label in ("Node", "Node ID", "Location", "Zone", "Added"):
        assert f'row("{label}"' in script
    assert 'row("Component", component.display_name)' in script
    assert 'row("Component ID", component.connected_component_id)' in script
    assert 'row("Component ID", component.definition_key)' not in script
    assert 'method: "PATCH"' in script
    assert "label:" in script and "location:" in script and "zone:" in script
    assert "definition_key:" not in script
    assert "capability.capability_instance_id" in script
    assert "<th>Instance ID</th>" in page
    assert 'class="component-detail-layout"' in page
    assert ".component-detail-layout { display:grid; gap:20px; }" in styles


def test_component_library_uses_styled_delete_dialog(client):
    page = client.get("/components").get_data(as_text=True)
    script = client.get("/static/components.js").get_data(as_text=True)

    assert "confirm(" not in script
    assert 'id="deleteComponentDialog"' in page
    assert 'id="deleteComponentForm"' in page
    assert 'id="deleteComponentError"' in page
    assert "Historical removed component records will be preserved." in page
    assert 'document.getElementById("deleteComponentTitle").textContent' in script
    assert 'document.getElementById("cancelDeleteComponent").onclick' in script
    assert 'method: "DELETE"' in script
    assert 'document.getElementById("deleteComponentError").textContent = result.error' in script
    assert 'document.getElementById("deleteComponentDialog").close()' in script
    assert "load();" in script


def test_legacy_dashboard_does_not_guess_connected_component_sources(client):
    script = client.get("/static/script.js").get_data(as_text=True)

    create_node(client)
    component = client.post("/api/nodes/node-a/components", json={
        "definition_key": "te-ms8607", "label": "Outside Sensor"
    }).get_json()
    before = client.get("/api/readings?node_id=node-a").get_json()
    client.patch(f'/api/nodes/node-a/components/{component["connected_component_id"]}', json={
        "label": "Weather Mast"
    })
    after = client.get("/api/readings?node_id=node-a").get_json()
    assert after == before
    assert client.get("/api/nodes/node-a/components").get_json()[0]["label"] == "Weather Mast"
    assert 'outside_temperature: "Outside Temperature"' in script
    assert 'enclosure_temperature: "Enclosure Temperature"' in script
    assert "/api/components" not in script
    assert "capability_instances" not in script
