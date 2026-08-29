import sqlite3

from app import database
from app.hardware_platforms import CAPABILITIES


EXPECTED_OUTPUT_CAPABILITIES = {
    "digital_input", "digital_output", "pwm", "i2c_sda", "i2c_scl",
    "spi_mosi", "spi_miso", "spi_sck", "spi_cs", "uart_tx", "uart_rx",
}
EXPECTED_INPUT_ONLY_CAPABILITIES = {
    "digital_input", "adc", "spi_miso", "uart_rx",
}
EXPECTED_HELTEC_RESOURCES = [
    1, 2, 3, 4, 5, 6, 7, 19, 20, 26, 33, 34, 38, 39, 40, 41, 42, 45, 46, 47, 48,
]
EXPECTED_HELTEC_ADC = {1, 2, 3, 4, 5, 6, 7, 19, 20}
EXPECTED_HELTEC_MATRIX = {
    f"GPIO{pin}": EXPECTED_OUTPUT_CAPABILITIES
    | ({"adc"} if pin in EXPECTED_HELTEC_ADC else set())
    for pin in EXPECTED_HELTEC_RESOURCES
}
EXPECTED_AZ_RESOURCES = [
    0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 23,
    25, 26, 27, 32, 33, 34, 35, 36, 39,
]
EXPECTED_AZ_ADC = {0, 2, 4, 12, 13, 14, 15, 25, 26, 27, 32, 33, 34, 35, 36, 39}
EXPECTED_AZ_DAC = {25, 26}
EXPECTED_AZ_INPUT_ONLY = {34, 35, 36, 39}
EXPECTED_AZ_MATRIX = {
    f"GPIO{pin}": (
        EXPECTED_INPUT_ONLY_CAPABILITIES
        if pin in EXPECTED_AZ_INPUT_ONLY
        else EXPECTED_OUTPUT_CAPABILITIES
        | ({"adc"} if pin in EXPECTED_AZ_ADC else set())
        | ({"dac"} if pin in EXPECTED_AZ_DAC else set())
    )
    for pin in EXPECTED_AZ_RESOURCES
}


def platform_payload(**changes):
    value={"display_name":"Custom Controller","manufacturer":"Example","model":"C1","mcu":"STM32",
           "revision":None,"description":None,
           "resources":[{"resource":"GPIO21","capabilities":["digital_input","digital_output","pwm"]}]}
    value.update(changes);return value


def seeded(client, name):
    return next(x for x in client.get('/api/hardware-platforms').get_json() if x['display_name']==name)


def test_schema_seed_and_startup_are_idempotent(isolated_database, client):
    database.init_db()
    platforms=client.get('/api/hardware-platforms').get_json()
    assert len(platforms)==2
    with sqlite3.connect(isolated_database) as conn:
        assert conn.execute('SELECT COUNT(*) FROM hardware_platforms').fetchone()[0]==2
        assert {'hardware_platform_resources','hardware_resource_capabilities'} <= {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert 'hardware_platform_id' in {r[1] for r in conn.execute('PRAGMA table_info(nodes)')}
        schema = conn.execute("""SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = 'hardware_resource_capabilities'""").fetchone()[0]
        assert 'check' not in schema.casefold()
        columns = {row[1]: row for row in conn.execute(
            'PRAGMA table_info(hardware_resource_capabilities)'
        )}
        assert columns['hardware_resource_id'][3] == 1
        assert columns['capability'][3] == 1
        assert {columns['hardware_resource_id'][5], columns['capability'][5]} == {1, 2}
        foreign_keys = conn.execute(
            'PRAGMA foreign_key_list(hardware_resource_capabilities)'
        ).fetchall()
        assert any(row[2] == 'hardware_platform_resources'
                   and row[3] == 'hardware_resource_id'
                   and row[4] == 'id'
                   and row[6].upper() == 'CASCADE' for row in foreign_keys)


def test_legacy_migration_aliases_and_preserves_node_ids(tmp_path, monkeypatch):
    path=tmp_path/'legacy.db';conn=sqlite3.connect(path)
    conn.execute('CREATE TABLE nodes(id INTEGER PRIMARY KEY,node_id TEXT UNIQUE,name TEXT,location TEXT,node_type TEXT,hardware_model TEXT,created_at TEXT)')
    conn.executemany("INSERT INTO nodes VALUES(?,?,?,?,?,?,?)",[(7,'heltec','h',None,'esp','heltec-wifi-lora-32-v3','x'),(8,'az','a',None,'esp','az-delivery-esp32-devkitc-v2','x'),(9,'other','o',None,'esp','unknown','x'),(10,'missing','m',None,'esp',None,'x')]);conn.commit();conn.close()
    monkeypatch.setattr(database,'DB_NAME',str(path));database.init_db();database.init_db()
    with sqlite3.connect(path) as conn:
        rows=conn.execute('SELECT id,node_id,hardware_platform_id FROM nodes ORDER BY id').fetchall()
    assert [r[:2] for r in rows]==[(7,'heltec'),(8,'az'),(9,'other'),(10,'missing')]
    assert rows[0][2].startswith('hp_') and rows[1][2].startswith('hp_')
    assert rows[2][2] is None and rows[3][2] is None


def test_crud_identity_duplicates_and_validation(client):
    first=client.post('/api/hardware-platforms',json=platform_payload()).get_json()
    second=client.post('/api/hardware-platforms',json=platform_payload()).get_json()
    assert first['hardware_platform_id'].startswith('hp_') and first['hardware_platform_id']!=second['hardware_platform_id']
    assert client.get(f"/api/hardware-platforms/{first['hardware_platform_id']}").get_json()['resources'][0]['capabilities']==['digital_input','digital_output','pwm']
    assert client.patch(f"/api/hardware-platforms/{first['hardware_platform_id']}",json={'manufacturer':'Changed','resources':[{'resource':'GPIO3','capabilities':['adc']}]}).status_code==200
    assert client.patch(f"/api/hardware-platforms/{first['hardware_platform_id']}",json={'hardware_platform_id':'hp_changed'}).status_code==400
    assert client.post('/api/hardware-platforms',json=platform_payload(manufacturer='')).status_code==400
    assert client.delete(f"/api/hardware-platforms/{first['hardware_platform_id']}").status_code==200


def test_capability_vocabulary_is_enforced_by_the_api(client):
    invalid = client.post('/api/hardware-platforms', json=platform_payload(
        resources=[{'resource': 'GPIO1', 'capabilities': ['arbitrary']}]
    ))
    assert invalid.status_code == 400
    valid = client.post('/api/hardware-platforms', json=platform_payload(
        display_name='All current capabilities',
        resources=[{'resource': 'PA9', 'capabilities': list(CAPABILITIES)}]
    ))
    assert valid.status_code == 201
    assert set(valid.get_json()['resources'][0]['capabilities']) == set(CAPABILITIES)


def test_assignment_freezes_technical_meaning_permanently(client, isolated_database):
    created=client.post('/api/hardware-platforms',json=platform_payload()).get_json();pid=created['hardware_platform_id']
    database.update_device_metadata('node-a',{'node_type':'controller'})
    assigned=client.put('/api/nodes/node-a/hardware-platform',json={'hardware_platform_id':pid})
    assert assigned.status_code==200 and assigned.get_json()['hardware_platform']['hardware_platform_id']==pid
    assert client.put('/api/nodes/node-a/hardware-platform',json={'hardware_platform_id':pid}).status_code==200
    other=seeded(client,'Heltec WiFi LoRa 32 V3.2')['hardware_platform_id']
    assert client.put('/api/nodes/node-a/hardware-platform',json={'hardware_platform_id':other}).status_code==409
    for payload in ({'manufacturer':'Nope'},{'model':'Nope'},{'mcu':'Nope'},{'revision':'Nope'},{'resources':[]},{'resources':[{'resource':'GPIO21','capabilities':['adc']}]}):
        assert client.patch(f'/api/hardware-platforms/{pid}',json=payload).status_code==400
    assert client.patch(f'/api/hardware-platforms/{pid}',json={'display_name':'Renamed','description':'Editable'}).status_code==200
    assert client.delete(f'/api/hardware-platforms/{pid}').status_code==409
    with sqlite3.connect(isolated_database) as conn: conn.execute("DELETE FROM nodes WHERE node_id='node-a'");conn.commit()
    assert client.patch(f'/api/hardware-platforms/{pid}',json={'manufacturer':'Still locked'}).status_code==400
    assert client.delete(f'/api/hardware-platforms/{pid}').status_code==409


def test_seed_resource_names_and_exact_matrices(client):
    heltec=seeded(client,'Heltec WiFi LoRa 32 V3.2');az=seeded(client,'AZ-Delivery ESP32 DevKitC V2')
    heltec_matrix = {item['resource']: set(item['capabilities']) for item in heltec['resources']}
    az_matrix = {item['resource']: set(item['capabilities']) for item in az['resources']}
    assert [item['resource'] for item in heltec['resources']] == [
        f"GPIO{pin}" for pin in EXPECTED_HELTEC_RESOURCES
    ]
    assert [item['resource'] for item in az['resources']] == [
        f"GPIO{pin}" for pin in EXPECTED_AZ_RESOURCES
    ]
    assert heltec_matrix == EXPECTED_HELTEC_MATRIX
    assert az_matrix == EXPECTED_AZ_MATRIX
    assert all(set(item['capabilities']) <= set(CAPABILITIES)
               for item in heltec['resources'] + az['resources'])
    assert len(heltec['resources'])==21 and len(az['resources'])==26
    assert all('dac' not in r['capabilities'] for r in heltec['resources'])
    assert {r['resource'] for r in az['resources'] if 'dac' in r['capabilities']}=={'GPIO25','GPIO26'}
    assert not ({f'GPIO{x}' for x in range(6,12)} & {r['resource'] for r in az['resources']})
    for resource in az['resources']:
        if resource['resource'] in {'GPIO34','GPIO35','GPIO36','GPIO39'}:
            assert set(resource['capabilities'])=={'digital_input','adc','spi_miso','uart_rx'}


def test_seed_matrices_are_not_the_global_capability_vocabulary():
    # The independently approved normal-output matrix deliberately excludes
    # ADC and DAC; it is not CAPABILITIES with only DAC removed.
    assert EXPECTED_OUTPUT_CAPABILITIES != set(CAPABILITIES) - {'dac'}


def test_generic_resource_identifiers_and_natural_sorting(client):
    identifiers = ['GPIO21', 'PA9', 'PB10', 'D13', 'A0', 'IO_5', 'PIN-4']
    resources = [{'resource': identifier, 'capabilities': ['digital_input']}
                 for identifier in reversed(identifiers)]
    created = client.post('/api/hardware-platforms', json=platform_payload(
        display_name='Generic labels', resources=resources
    ))
    assert created.status_code == 201
    assert [item['resource'] for item in created.get_json()['resources']] == [
        'A0', 'D13', 'GPIO21', 'IO_5', 'PA9', 'PB10', 'PIN-4'
    ]


def test_invalid_and_duplicate_resource_identifiers_are_rejected(client):
    for identifier in ('', '   ', 'GPIO 21', 'pin/name', '<script>'):
        response = client.post('/api/hardware-platforms', json=platform_payload(
            resources=[{'resource': identifier, 'capabilities': ['digital_input']}]
        ))
        assert response.status_code == 400
    duplicate = client.post('/api/hardware-platforms', json=platform_payload(
        resources=[
            {'resource': 'PA9', 'capabilities': ['digital_input']},
            {'resource': ' PA9 ', 'capabilities': ['digital_output']},
        ]
    ))
    assert duplicate.status_code == 400


def test_library_routes_navigation_editor_and_technical_tile(client):
    assert client.get('/hardware-platforms').status_code==200
    nodes=client.get('/nodes').get_data(as_text=True)
    assert nodes.index('href="/"') < nodes.index('href="/nodes"') < nodes.index('href="/fleet/organization"') < nodes.index('href="/components"') < nodes.index('href="/hardware-platforms"')
    page=client.get('/hardware-platforms').get_data(as_text=True)
    assert all(label in page for label in (
        'Pins are board-exposed programmable signals.',
        'Technical identity and pins are permanently locked because this definition has been assigned to a Node. Only Display Name and Description can be changed.',
        '<th>Pins</th>', 'Programmable Pins', '<th>Pin</th>', '+ Add Pin',
    ))
    assert all(label not in page for label in (
        'Resources are board-exposed programmable signals.',
        'Technical identity and resources are permanently locked',
        '<th>Resources</th>', 'Programmable Resources', '<th>Resource</th>', '+ Add Resource',
    ))
    script=client.get('/static/hardware_platforms.js').get_data(as_text=True)
    assert "['digital_input', 'Digital In']" in script
    assert "['Select all', '']" in script and 'Digital I/O' not in script
    assert "tr.querySelectorAll('[data-capability]')" in script
    assert 'selectAll.indeterminate = checkedCount > 0' in script
    assert "querySelectorAll('[data-capability]:checked')" in script
    assert 'digital_io' not in script and 'select_all' not in script
    assert script.count("['") >= 13
    assert all(value in script for value in CAPABILITIES)
    assert 'className = \'kebab-button\'' in script
    assert "menu.className = 'action-menu row-action-menu platform-action-menu'" in script
    assert "[['View / Edit Details', () => openForm(item)]]" in script
    assert "[['Edit', () => openForm(item)], ['Delete', () => deletePlatform(item)]]" in script
    technical=client.get('/static/node_technical.js').get_data(as_text=True)
    assert 'node.hardware_platform?.display_name' in technical and 'Hardware model' not in technical


def test_hardware_platform_usage_count_and_library_fleet_link(client):
    for node_id in ('assigned-a', 'assigned-b', 'unassigned'):
        database.update_device_metadata(node_id, {'node_type': 'controller'})
    platform = seeded(client, 'Heltec WiFi LoRa 32 V3.2')
    for node_id in ('assigned-a', 'assigned-b'):
        assert client.put(f'/api/nodes/{node_id}/hardware-platform', json={
            'hardware_platform_id': platform['hardware_platform_id']
        }).status_code == 200
    refreshed = seeded(client, 'Heltec WiFi LoRa 32 V3.2')
    assert refreshed['active_node_count'] == 2
    overview = {item['node_id']: item for item in client.get('/api/nodes/overview').get_json()}
    expected = {'hardware_platform_id': platform['hardware_platform_id'],
                'display_name': 'Heltec WiFi LoRa 32 V3.2'}
    assert overview['assigned-a']['hardware_platform'] == expected
    assert overview['assigned-b']['hardware_platform'] == expected
    assert overview['unassigned']['hardware_platform'] is None
    page = client.get('/hardware-platforms').get_data(as_text=True)
    script = client.get('/static/hardware_platforms.js').get_data(as_text=True)
    assert '<th>Nodes</th>' in page and '<th>Status</th>' not in page
    assert '/nodes?hardware_platform=' in script
    assert 'item.active_node_count' in script
    assert "usageLink.className = 'usage-count-link'" in script
