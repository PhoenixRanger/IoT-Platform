import sqlite3

from app.database import save_measurements


def create_node(client, node_id="runtime-node"):
    save_measurements(node_id, {"temperature": 20})


def add_component(client, node_id="runtime-node", definition_key="te-ms8607", label="Sensor"):
    return client.post(f"/api/nodes/{node_id}/components", json={
        "definition_key": definition_key, "label": label, "location": None, "zone": None,
    }).get_json()


def custom_definition(client, key="custom-runtime"):
    response = client.post("/api/components", json={
        "definition_key": key, "display_name": "Custom Sensor", "manufacturer": None,
        "model": None, "component_class": "sensor", "interfaces": ["i2c"],
        "capabilities": ["temperature_measurement"],
    })
    assert response.status_code == 201
    return response.get_json()


def test_registry_metadata_and_schema_constraints(client, isolated_database):
    setting = client.get("/api/runtime-settings").get_json()[0]
    assert setting == {
        "setting_key": "measurement_interval", "display_name": "Measurement Interval",
        "description": "Interval between requested measurement cycles for the Connected Component.",
        "value_type": "integer", "unit": "seconds", "minimum": 1,
        "maximum": 86400, "default_value": 60,
    }
    with sqlite3.connect(isolated_database) as connection:
        try:
            connection.execute("""INSERT INTO runtime_setting_definitions
                (setting_key,display_name,description,value_type,default_integer)
                VALUES ('measurement_interval','Duplicate','Duplicate','integer',60)""")
            assert False, "duplicate key accepted"
        except sqlite3.IntegrityError:
            pass


def test_builtin_retrofit_and_idempotency(client):
    from app.database import init_db
    init_db(); init_db()
    expected = {
        "te-ms8607": True, "aosong-dht22": True,
        "generic-analog-soil-moisture-sensor": True,
        "generic-mosfet-switch-module": False,
    }
    for key, supported in expected.items():
        response = client.get(f"/api/components/{key}/runtime-settings")
        assert response.status_code == 200
        assert bool(response.get_json()) is supported


def test_editable_supported_settings_add_read_remove_and_validation(client):
    custom_definition(client)
    url = "/api/components/custom-runtime/runtime-settings"
    assert client.put(url, json={"runtime_settings": ["measurement_interval"]}).status_code == 200
    assert client.get(url).get_json()[0]["setting_key"] == "measurement_interval"
    assert client.put(url, json={"runtime_settings": []}).get_json() == []
    assert client.put(url, json={"runtime_settings": ["unknown"]}).status_code == 400
    assert client.put(url, json={"runtime_settings": ["measurement_interval", "measurement_interval"]}).status_code == 400


def test_historical_use_locks_supported_settings_but_keeps_them_readable(client):
    create_node(client); custom_definition(client)
    url = "/api/components/custom-runtime/runtime-settings"
    client.put(url, json={"runtime_settings": ["measurement_interval"]})
    component = add_component(client, definition_key="custom-runtime")
    client.delete(f"/api/nodes/runtime-node/components/{component['connected_component_id']}")
    assert client.put(url, json={"runtime_settings": []}).status_code == 409
    assert client.get(url).get_json()[0]["setting_key"] == "measurement_interval"


def test_definition_support_flows_to_connected_component_effective_default(client):
    create_node(client)
    custom_definition(client)
    assert client.put(
        "/api/components/custom-runtime/runtime-settings",
        json={"runtime_settings": ["measurement_interval"]},
    ).status_code == 200
    component = add_component(client, definition_key="custom-runtime")

    configuration = client.get(
        "/api/nodes/runtime-node/runtime-configuration"
    ).get_json()
    configured = next(item for item in configuration["components"] if
                      item["connected_component_id"] == component["connected_component_id"])
    interval = configured["settings"]["measurement_interval"]
    assert interval["effective_value"] == 60
    assert interval["explicit_value"] is None
    assert interval["uses_default"] is True


def test_defaults_updates_revision_noop_and_ranges(client):
    create_node(client); component = add_component(client)
    node_url = "/api/nodes/runtime-node/runtime-configuration"
    update_url = f"/api/nodes/runtime-node/components/{component['connected_component_id']}/runtime-configuration"
    initial = client.get(node_url).get_json()
    assert initial["runtime_configuration_revision"] == 0
    configured = initial["components"][0]
    assert configured["enabled"] is True
    assert configured["settings"]["measurement_interval"]["effective_value"] == 60
    assert configured["settings"]["measurement_interval"]["explicit_value"] is None
    assert client.put(update_url, json={"enabled": True, "settings": {"measurement_interval": 60}}).get_json()["changed"] is False
    changed = client.put(update_url, json={"enabled": False, "settings": {"measurement_interval": 300}})
    assert changed.status_code == 200
    assert changed.get_json()["runtime_configuration_revision"] == 1
    assert changed.get_json()["enabled"] is False
    assert changed.get_json()["settings"]["measurement_interval"]["explicit_value"] == 300
    assert client.put(update_url, json={"enabled": False, "settings": {"measurement_interval": 300}}).get_json()["runtime_configuration_revision"] == 1
    for value, accepted in ((1, True), (86400, True), (0, False), (86401, False), (-1, False), (1.5, False), ("60", False)):
        response = client.put(update_url, json={"enabled": False, "settings": {"measurement_interval": value}})
        assert (response.status_code == 200) is accepted


def test_atomic_invalid_mutation_preserves_state_and_revision(client):
    create_node(client); component = add_component(client)
    update_url = f"/api/nodes/runtime-node/components/{component['connected_component_id']}/runtime-configuration"
    client.put(update_url, json={"enabled": True, "settings": {"measurement_interval": 120}})
    failed = client.put(update_url, json={"enabled": False, "settings": {"measurement_interval": 0, "unknown": 4}})
    assert failed.status_code == 400 and len(failed.get_json()["validation_errors"]) == 2
    state = client.get("/api/nodes/runtime-node/runtime-configuration").get_json()
    assert state["runtime_configuration_revision"] == 1
    assert state["components"][0]["enabled"] is True
    assert state["components"][0]["settings"]["measurement_interval"]["effective_value"] == 120


def test_wrong_node_and_unsupported_known_setting(client):
    create_node(client); create_node(client, "other-node"); component = add_component(client)
    url = f"/api/nodes/other-node/components/{component['connected_component_id']}/runtime-configuration"
    assert client.put(url, json={"enabled": True, "settings": {}}).status_code == 404
    actuator = add_component(client, definition_key="generic-mosfet-switch-module", label="Switch")
    url = f"/api/nodes/runtime-node/components/{actuator['connected_component_id']}/runtime-configuration"
    assert client.put(url, json={"enabled": True, "settings": {"measurement_interval": 60}}).status_code == 400


def test_unmapped_runtime_save_does_not_change_mapping(client):
    create_node(client); component = add_component(client)
    mapping_url = f"/api/nodes/runtime-node/components/{component['connected_component_id']}/hardware-mapping"
    before = client.get(mapping_url).get_json()
    runtime_url = f"/api/nodes/runtime-node/components/{component['connected_component_id']}/runtime-configuration"
    assert client.put(runtime_url, json={"enabled": False, "settings": {"measurement_interval": 90}}).status_code == 200
    after = client.get(mapping_url).get_json()
    assert before == after
    assert after["mapping_state"] == "Unmapped"


def test_disable_does_not_remove_capabilities_or_telemetry(client, isolated_database):
    create_node(client); component = add_component(client)
    instance_ids = [item["capability_instance_id"] for item in component["capability_instances"]]
    url = f"/api/nodes/runtime-node/components/{component['connected_component_id']}/runtime-configuration"
    client.put(url, json={"enabled": False, "settings": {"measurement_interval": 60}})
    current = client.get(f"/api/nodes/runtime-node/components/{component['connected_component_id']}").get_json()
    assert [item["capability_instance_id"] for item in current["capability_instances"]] == instance_ids
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM measurements WHERE node_id='runtime-node'").fetchone()[0] == 1


def test_configuration_ui_contract(client):
    create_node(client)
    page = client.get("/nodes/runtime-node/configuration").get_data(as_text=True)
    technical = client.get("/nodes/runtime-node/technical").get_data(as_text=True)
    script = client.get("/static/node_configuration.js").get_data(as_text=True)
    assert "Physical" in page and "Runtime" in page and "Server-side" in page
    assert "Hardware Platform" not in page and 'id="platformDetails"' not in page
    assert "Components" in page and "Hardware Allocation" in page
    assert "Change Hardware Platform" not in page
    assert "Reported Configuration" not in page and "Drift" not in page
    assert "View Configuration" in technical and "+ Add Component" not in technical
    assert "Object.values(component.settings)" in script
    assert "setting.display_name" in script and "setting.default_value" in script
    assert "setting.minimum" in script and "setting.maximum" in script
    assert 'id="runtimeSave"' in page and 'id="runtimeDiscard"' in page
    assert page.count("Save Changes") == 1
    assert "runtimeSave.disabled=!dirty.length||!valid" in script
    assert "runtimeDiscard.onclick=()=>renderRuntime()" in script
    assert 'form.addEventListener("change",updateRuntimeDirtyState)' in script
    assert "dirtyRuntimeComponents()" in script
    assert "body:JSON.stringify(runtimeCandidate(component))" in script
    assert "enabled:" in script and "settings" in script
    assert "runtimeRevision.textContent=result.runtime_configuration_revision" in script
    assert 'empty.textContent="No runtime settings"' in script


def test_known_legacy_definition_retrofit_is_bounded_and_identity_safe(
        client, isolated_database):
    from app import database

    create_node(client)
    timestamp = "2026-01-01 00:00:00"
    legacy_keys = ("ms8607xx", "def_31ead969f7")
    unrelated_key = "unrelated-locked-sensor"
    with sqlite3.connect(isolated_database) as connection:
        capability_id = connection.execute("""SELECT id FROM capabilities
            WHERE capability_key='temperature_measurement'""").fetchone()[0]
        definitions = list(zip(legacy_keys, ("MS8607xx", "DHT22"))) + [
            (unrelated_key, "Unrelated Sensor")
        ]
        for key, name in definitions:
            cursor = connection.execute("""INSERT INTO component_definitions
                (definition_key,display_name,component_class,created_at,updated_at)
                VALUES (?,?,'sensor',?,?)""", (key, name, timestamp, timestamp))
            connection.execute("INSERT INTO component_capabilities VALUES (?,?)",
                               (cursor.lastrowid, capability_id))
        connection.commit()

    components = {
        key: add_component(client, definition_key=key, label=key)
        for key in (*legacy_keys, unrelated_key)
    }
    with sqlite3.connect(isolated_database) as connection:
        node_db_id = connection.execute(
            "SELECT id FROM nodes WHERE node_id='runtime-node'"
        ).fetchone()[0]
        connection.execute("""INSERT INTO node_runtime_configuration_revisions
            (node_db_id,revision,updated_at) VALUES (?,7,?)""", (node_db_id, timestamp))
        connection.commit()
        before_parents = dict(connection.execute("""SELECT definition.definition_key,
            connected.connected_component_id FROM connected_components connected
            JOIN component_definitions definition ON definition.id=connected.component_definition_id
            WHERE definition.definition_key IN (?,?,?)""", (*legacy_keys, unrelated_key)))
        before_children = list(connection.execute("""SELECT capability_instance_id,
            connected_component_id FROM component_capability_instances ORDER BY id"""))
        before_mappings = list(connection.execute("""SELECT connected_component_id,
            endpoint_id,hardware_resource_id,active
            FROM connected_component_hardware_mappings ORDER BY id"""))

    database.init_db()
    database.init_db()

    for key in legacy_keys:
        supported = client.get(f"/api/components/{key}/runtime-settings").get_json()
        assert [item["setting_key"] for item in supported] == ["measurement_interval"]
        assert client.put(
            f"/api/components/{key}/runtime-settings",
            json={"runtime_settings": []},
        ).status_code == 409
    assert client.get(
        f"/api/components/{unrelated_key}/runtime-settings"
    ).get_json() == []
    with sqlite3.connect(isolated_database) as connection:
        associations = connection.execute("""SELECT COUNT(*)
            FROM component_definition_runtime_settings supported
            JOIN component_definitions definition
              ON definition.id=supported.component_definition_id
            WHERE definition.definition_key IN (?,?)""", legacy_keys).fetchone()[0]
        assert associations == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM connected_component_runtime_setting_values"
        ).fetchone()[0] == 0
        assert connection.execute("""SELECT revision
            FROM node_runtime_configuration_revisions WHERE node_db_id=?""",
            (node_db_id,)).fetchone()[0] == 7
        after_parents = dict(connection.execute("""SELECT definition.definition_key,
            connected.connected_component_id FROM connected_components connected
            JOIN component_definitions definition ON definition.id=connected.component_definition_id
            WHERE definition.definition_key IN (?,?,?)""", (*legacy_keys, unrelated_key)))
        after_children = list(connection.execute("""SELECT capability_instance_id,
            connected_component_id FROM component_capability_instances ORDER BY id"""))
        after_mappings = list(connection.execute("""SELECT connected_component_id,
            endpoint_id,hardware_resource_id,active
            FROM connected_component_hardware_mappings ORDER BY id"""))
    assert after_parents == before_parents
    assert after_children == before_children
    assert after_mappings == before_mappings
    assert components["ms8607xx"]["connected_component_id"] == before_parents["ms8607xx"]

    configuration = client.get(
        "/api/nodes/runtime-node/runtime-configuration"
    ).get_json()
    configured = next(item for item in configuration["components"] if
                      item["connected_component_id"] == before_parents["ms8607xx"])
    assert configured["settings"]["measurement_interval"] == {
        "setting_key": "measurement_interval",
        "display_name": "Measurement Interval",
        "description": "Interval between requested measurement cycles for the Connected Component.",
        "value_type": "integer", "unit": "seconds", "minimum": 1,
        "maximum": 86400, "default_value": 60, "explicit_value": None,
        "effective_value": 60, "uses_default": True,
    }
