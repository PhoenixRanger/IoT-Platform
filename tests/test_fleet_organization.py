import sqlite3

import pytest

from app.database import (
    create_definition,
    delete_definition,
    get_node_organization,
    get_nodes_overview,
    list_definitions,
    mutate_organization,
    rename_definition,
    save_measurements,
)


def test_organization_migration_schema_indexes_and_foreign_keys(isolated_database):
    with sqlite3.connect(isolated_database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"groups", "tags", "node_groups", "node_tags"} <= tables
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        group_indexes = {row[1] for row in connection.execute("PRAGMA index_list(node_groups)")}
        tag_indexes = {row[1] for row in connection.execute("PRAGMA index_list(node_tags)")}
        assert "idx_node_groups_group" in group_indexes
        assert "idx_node_tags_tag" in tag_indexes
        foreign_keys = connection.execute("PRAGMA foreign_key_list(node_groups)").fetchall()
        assert all(row[6] == "CASCADE" for row in foreign_keys)


@pytest.mark.parametrize("kind", ["group", "tag"])
def test_definition_crud_duplicate_names_counts_and_cascade(kind, isolated_database):
    save_measurements("node", {"temperature": 20})
    definition = create_definition(kind, "  Greenhouse  ")
    assert definition["name"] == "Greenhouse"
    with pytest.raises(ValueError):
        create_definition(kind, "greenHOUSE")
    mutate_organization(["node"], kind, [definition["id"]], "add")
    mutate_organization(["node"], kind, [definition["id"]], "add")
    assert list_definitions(kind)[0]["node_count"] == 1
    assert rename_definition(kind, definition["id"], "North Field")
    assert get_node_organization("node")[f"{kind}s"][0]["name"] == "North Field"
    assert delete_definition(kind, definition["id"])
    assert get_node_organization("node")[f"{kind}s"] == []
    with sqlite3.connect(isolated_database) as connection:
        assert connection.execute("SELECT 1 FROM nodes WHERE node_id='node'").fetchone()


def test_individual_and_bulk_memberships_are_idempotent_and_validate(isolated_database):
    for node_id in ("one", "two"):
        save_measurements(node_id, {"temperature": 20})
    groups = [create_definition("group", name) for name in ("A", "B")]
    tags = [create_definition("tag", name) for name in ("solar", "outdoor")]
    mutate_organization(["one"], "group", [item["id"] for item in groups], "add")
    mutate_organization(["one", "two"], "group", [groups[0]["id"]], "add")
    mutate_organization(["one", "two"], "tag", [item["id"] for item in tags], "add")
    mutate_organization(["one", "two"], "tag", [tags[0]["id"]], "remove")
    mutate_organization(["one", "two"], "group", [groups[1]["id"]], "remove")
    assert [item["name"] for item in get_node_organization("one")["groups"]] == ["A"]
    assert [item["name"] for item in get_node_organization("two")["tags"]] == ["outdoor"]
    with pytest.raises(LookupError):
        mutate_organization(["missing"], "group", [groups[0]["id"]], "add")
    with pytest.raises(LookupError):
        mutate_organization(["one"], "tag", [999], "add")


def test_definition_and_membership_apis(client):
    save_measurements("node", {"temperature": 20})
    assert client.post("/api/groups", json={"name": " "}).status_code == 400
    group = client.post("/api/groups", json={"name": "Greenhouse"}).get_json()
    tag = client.post("/api/tags", json={"name": "solar"}).get_json()
    assert client.post("/api/groups", json={"name": "greenhouse"}).status_code == 400
    payload = {"kind": "group", "definition_ids": [group["id"]], "operation": "add"}
    assert client.post("/api/nodes/node/organization", json=payload).status_code == 200
    bulk = {"node_ids": ["node"], "kind": "tag", "definition_ids": [tag["id"]], "operation": "add"}
    assert client.post("/api/fleet/organization", json=bulk).status_code == 200
    overview = client.get("/api/nodes/overview").get_json()[0]
    assert overview["groups"] == [{"id": group["id"], "name": "Greenhouse"}]
    assert overview["tags"] == [{"id": tag["id"], "name": "solar"}]
    assert client.post("/api/fleet/organization", json={**bulk, "node_ids": ["missing"]}).status_code == 404
    assert client.patch(f"/api/groups/{group['id']}", json={"name": "Field"}).status_code == 200
    assert client.delete(f"/api/tags/{tag['id']}").status_code == 200


def test_overview_expected_capabilities_and_ui_filter_selection_contract(client):
    save_measurements("node", {"temperature": 20})
    client.put("/api/nodes/node/capabilities", json={"expected": ["wifi"]})
    assert get_nodes_overview()[0]["expected_capabilities"] == []
    page = client.get("/nodes").get_data(as_text=True)
    script = client.get("/static/nodes.js").get_data(as_text=True)
    for family in ("Group", "Tag", "Capability", "Hardware Platform", "Component",
                   "Runtime Status", "Overall Health"):
        assert family in script
    assert 'const runtimeStatusOptions = ["online", "offline", "unknown", "disabled"]' in script
    assert 'const overallHealthOptions = ["healthy", "capability_mismatch", "offline", "unknown", "disabled"]' in script
    assert 'overallHealthOptions = ["healthy", "capability_mismatch", "online"' not in script
    assert "activeFilterFamily === null" in script
    assert "renderFilterFamilyMenu(panel)" in script
    assert "renderFilterFamilyValues(panel, activeFilterFamily)" in script
    assert 'search.type = "search"' in script
    assert 'optionList.querySelectorAll("label")' in script
    assert 'hardware_platform: new Set()' in script
    assert 'component: new Set()' in script
    assert 'item.hardware_platform_id, item.display_name' in script
    assert 'item.definition_key, item.display_name' in script
    assert 'node.components.map(item => item.definition_key)' in script
    assert 'params.getAll(family)' in script
    assert 'if (valid.has(value)) filters[family].add(value)' in script
    assert 'window.addEventListener("popstate"' in script
    assert 'fetch("/api/hardware-platforms")' in script
    assert 'fetch("/api/components")' in script
    assert "Object.entries(filterOptions()).map" not in script
    assert "Category" not in page
    assert "const selectedNodeIds = new Set()" in script
    assert "visibleNodes().forEach" in script
    assert "reconcileSelection(nodes)" in script
    assert "if (!visibleIds.has(nodeId)) selectedNodeIds.delete(nodeId)" in script
    assert "selected ·" not in script and "visible`" not in script
    assert "selectedNodeIds.clear()" in script
    assert "Bulk Action" in page
    assert all(action in page for action in ("Add to Group", "Remove from Group", "Apply Tag", "Remove Tag"))


def test_fleet_organization_and_node_views(client):
    organization = client.get("/fleet/organization")
    assert organization.status_code == 200
    assert b"Fleet Organization" in organization.data
    details = client.get("/nodes/missing").get_data(as_text=True)
    technical = client.get("/nodes/missing/technical").get_data(as_text=True)
    assert 'id="organization"' in details
    assert "Runtime Status" not in details
    assert "Runtime Status" in technical and "Capabilities" in technical


def test_top_level_pages_share_canonical_primary_navigation(client):
    destinations = [
        ('/', 'Dashboard'), ('/nodes', 'All Nodes'),
        ('/fleet/organization', 'Manage Groups &amp; Tags'),
        ('/components', 'Component Library'),
        ('/hardware-platforms', 'Hardware Platform Library'),
    ]
    active_sections = {
        '/': 'dashboard', '/nodes': 'nodes', '/fleet/organization': 'organization',
        '/components': 'components', '/hardware-platforms': 'hardware_platforms',
    }
    partial = open('templates/_primary_nav.html', encoding='utf-8').read()
    for route, _ in destinations:
        page = client.get(route).get_data(as_text=True)
        assert 'class="primary-nav"' in page
        positions = [page.index(f'href="{href}"') for href, _ in destinations]
        assert positions == sorted(positions)
        assert all(label in page for _, label in destinations)
        active_href = dict((key, href) for key, href, _ in [
            ('dashboard', '/', 'Dashboard'), ('nodes', '/nodes', 'All Nodes'),
            ('organization', '/fleet/organization', 'Manage Groups & Tags'),
            ('components', '/components', 'Component Library'),
            ('hardware_platforms', '/hardware-platforms', 'Hardware Platform Library'),
        ])[active_sections[route]]
        active_link_start = page.rfind('<a ', 0, page.index(f'href="{active_href}"') + 1)
        active_link_end = page.index('</a>', active_link_start)
        active_link = page[active_link_start:active_link_end]
        assert 'button-primary' in active_link and 'aria-current="page"' in active_link
    assert "include '_primary_nav.html'" in open('templates/index.html', encoding='utf-8').read()
    assert 'primary-nav' in partial
    for route in ('/nodes/missing', '/nodes/missing/technical'):
        assert 'class="primary-nav"' not in client.get(route).get_data(as_text=True)


def test_usage_pill_and_row_menu_overlay_contract(client):
    styles = client.get('/static/style.css').get_data(as_text=True)
    assert '.usage-count-link {' in styles
    assert '.usage-count-link:hover' in styles
    assert '.usage-count-link:focus-visible' in styles
    assert '.component-table-wrapper { overflow:visible; }' in styles
    assert '.component-table tr.menu-open { position:relative; z-index:' in styles
    platform_page = client.get('/hardware-platforms').get_data(as_text=True)
    assert 'class="responsive-table component-table-wrapper"' in platform_page
    assert '<span class="visually-hidden">Actions</span>' in platform_page


def test_node_views_share_node_specific_navigation(client):
    node_id = "windowsill_irrigation_001"
    save_measurements(node_id, {"temperature": 20})
    dashboard = client.get(f"/?node_id={node_id}").get_data(as_text=True)
    details = client.get(f"/nodes/{node_id}").get_data(as_text=True)
    technical = client.get(f"/nodes/{node_id}/technical").get_data(as_text=True)
    dashboard_script = client.get("/static/script.js").get_data(as_text=True)

    assert 'id="dashboardNodeTabs"' in dashboard
    assert 'id="dashboardTab" class="active"' in dashboard
    assert all(label in dashboard for label in ("Dashboard", "Details", "Technical"))
    assert "updateNodeNavigation()" in dashboard_script
    assert "encodeURIComponent(selectedNodeId)" in dashboard_script
    for page, active in ((details, "Details"), (technical, "Technical")):
        assert f'href="/?node_id={node_id}"' in page
        assert f'href="/nodes/{node_id}"' in page
        assert f'href="/nodes/{node_id}/technical"' in page
        assert f'class="active" href="/nodes/{node_id}{"/technical" if active == "Technical" else ""}">{active}' in page


def test_fleet_transient_menus_and_row_action_contract(client):
    page = client.get("/nodes").get_data(as_text=True)
    script = client.get("/static/nodes.js").get_data(as_text=True)
    styles = client.get("/static/style.css").get_data(as_text=True)

    assert "<th>Actions</th>" not in page
    assert "<th>Groups</th>" in page
    assert "<th>Tags</th>" in page
    assert "<th>Health</th>" in page
    assert "Groups / Tags" not in page
    assert 'class="fleet-menu-column"' in page
    assert 'class="filter-panel transient-menu"' in page
    assert 'class="action-menu transient-menu"' in page
    assert 'menuButton.textContent = "⋮"' in script
    assert all(f'"{label}"' in script for label in ("Dashboard", "Details", "Technical"))
    assert 'className = `button-link ${style}`' not in script
    assert 'document.addEventListener("click"' in script
    assert 'event.key === "Escape"' in script
    assert "closeTransientMenus(menu)" in script
    assert 'document.getElementById("filterControl").addEventListener("click", event => event.stopPropagation())' in script
    assert ".filter-panel *,.action-menu * { color:#111827; }" in styles
    assert ".membership-popover * { color:#111827; }" in styles
    assert ".fleet-table-card" in styles and "overflow: visible" in styles


def test_fleet_organization_dialog_cancel_controls_are_non_submitting(client):
    page = client.get("/fleet/organization").get_data(as_text=True)
    script = client.get("/static/fleet_organization.js").get_data(as_text=True)
    styles = client.get("/static/style.css").get_data(as_text=True)

    assert '<button id="cancelDefinition" type="button">Cancel</button>' in page
    assert '<button id="cancelDelete" type="button">Cancel</button>' in page
    assert 'class="button-primary" type="submit">Save</button>' in page
    assert 'type="submit" id="confirmDelete">Delete</button>' in page
    assert "formmethod=\"dialog\"" not in page
    assert 'document.getElementById("cancelDefinition").onclick' in script
    assert 'document.getElementById("definitionDialog").close()' in script
    assert 'document.getElementById("cancelDelete").onclick' in script
    assert 'document.addEventListener("click"' in script
    assert 'event.key === "Escape"' in script
    assert ".organization-tabs" in styles and "background:#f8fafc" in styles
    assert 'id="definitionError" class="error-message" role="alert" hidden' in page
    assert "setDefinitionError(result.error)" in script
    assert "error.hidden = !message" in script
    assert ".error-message:empty { display: none; }" in styles


def test_bulk_cancel_and_node_tab_styling_contract(client):
    page = client.get("/nodes").get_data(as_text=True)
    script = client.get("/static/nodes.js").get_data(as_text=True)
    styles = client.get("/static/style.css").get_data(as_text=True)

    assert '<button id="cancelBulk" type="button">Cancel</button>' in page
    assert 'document.getElementById("cancelBulk").onclick' in script
    assert 'document.getElementById("bulkDialog").close()' in script
    assert 'Select at least one ${currentBulkAction.endsWith("group") ? "group" : "tag"}.' in script
    assert ".node-tabs a { background:#f8fafc" in styles
    assert ".node-tabs .active { border-color:#2563eb" in styles
    assert "color:#111827" in styles
