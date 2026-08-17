const FLEET_REFRESH_INTERVAL_MS = 10000;
let fleetNodes = [];
let selectionMode = false;
const selectedNodeIds = new Set();

function visibleNodes() {
    const query = document.getElementById("nodeSearch").value.trim().toLocaleLowerCase();
    return fleetNodes.filter(node =>
        node.node_id.toLocaleLowerCase().includes(query) ||
        node.name.toLocaleLowerCase().includes(query)
    );
}

function healthLabel(health) {
    return health.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase());
}

function updateSelectionControls(nodes = visibleNodes()) {
    document.querySelectorAll(".selection-column").forEach(element => {
        element.hidden = !selectionMode;
    });
    document.getElementById("selectionToolbar").hidden = !selectionMode;
    document.getElementById("toggleSelection").textContent = selectionMode ? "Cancel" : "Select Nodes";
    document.getElementById("selectionCount").textContent = `${selectedNodeIds.size} ${selectedNodeIds.size === 1 ? "node" : "nodes"} selected`;

    // Select All intentionally targets only rows matching the current search.
    const allVisibleSelected = nodes.length > 0 && nodes.every(node => selectedNodeIds.has(node.node_id));
    document.getElementById("selectAllNodes").textContent = allVisibleSelected ? "Unselect All" : "Select All";
}

function createFleetRow(node) {
    const row = document.createElement("tr");
    const encodedNodeId = encodeURIComponent(node.node_id);

    const selectionCell = document.createElement("td");
    selectionCell.className = "selection-column";
    selectionCell.hidden = !selectionMode;
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selectedNodeIds.has(node.node_id);
    checkbox.setAttribute("aria-label", `Select ${node.name}`);
    checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedNodeIds.add(node.node_id);
        else selectedNodeIds.delete(node.node_id);
        updateSelectionControls();
    });
    selectionCell.appendChild(checkbox);

    const identityCell = document.createElement("td");
    const name = document.createElement("strong");
    name.textContent = node.name;
    const nodeId = document.createElement("small");
    nodeId.textContent = node.node_id;
    identityCell.append(name, nodeId);

    const tagsCell = document.createElement("td");
    tagsCell.textContent = "—";

    const healthCell = document.createElement("td");
    healthCell.className = "fleet-health";
    const indicator = document.createElement("span");
    indicator.className = `status-indicator status-indicator-${node.status}`;
    indicator.setAttribute("aria-hidden", "true");
    healthCell.append(indicator, document.createTextNode(healthLabel(node.health)));

    const actionsCell = document.createElement("td");
    actionsCell.className = "fleet-actions";
    const dashboardLink = document.createElement("a");
    dashboardLink.className = "button-link button-primary";
    dashboardLink.href = `/?node_id=${encodedNodeId}`;
    dashboardLink.textContent = "Dashboard";
    const detailsLink = document.createElement("a");
    detailsLink.className = "button-link button-secondary";
    detailsLink.href = `/nodes/${encodedNodeId}`;
    detailsLink.textContent = "Details";
    actionsCell.append(dashboardLink, detailsLink);

    row.append(selectionCell, identityCell, tagsCell, healthCell, actionsCell);
    return row;
}

function renderFleet() {
    const nodes = visibleNodes();
    const rows = document.getElementById("fleetRows");
    rows.replaceChildren(...nodes.map(createFleetRow));
    document.getElementById("emptyFleet").hidden = nodes.length !== 0;
    updateSelectionControls(nodes);
}

async function refreshFleet() {
    try {
        const response = await fetch("/api/nodes/overview");
        if (!response.ok) throw new Error("Fleet request failed");
        fleetNodes = await response.json();
        const currentIds = new Set(fleetNodes.map(node => node.node_id));
        selectedNodeIds.forEach(nodeId => {
            if (!currentIds.has(nodeId)) selectedNodeIds.delete(nodeId);
        });
        renderFleet();
        document.getElementById("fleetError").hidden = true;
    } catch (error) {
        console.error(error);
        document.getElementById("fleetError").hidden = false;
    }
}

document.getElementById("nodeSearch").addEventListener("input", renderFleet);
document.getElementById("toggleSelection").addEventListener("click", () => {
    if (selectionMode) selectedNodeIds.clear();
    selectionMode = !selectionMode;
    renderFleet();
});
document.getElementById("selectAllNodes").addEventListener("click", () => {
    const nodes = visibleNodes();
    const allVisibleSelected = nodes.length > 0 && nodes.every(node => selectedNodeIds.has(node.node_id));
    nodes.forEach(node => {
        if (allVisibleSelected) selectedNodeIds.delete(node.node_id);
        else selectedNodeIds.add(node.node_id);
    });
    renderFleet();
});

refreshFleet();
setInterval(refreshFleet, FLEET_REFRESH_INTERVAL_MS);
