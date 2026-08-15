const detailsRoot = document.getElementById("nodeDetails");
const nodeId = detailsRoot.dataset.nodeId;
const editButton = document.getElementById("editNode");
const saveButton = document.getElementById("saveNode");
const cancelButton = document.getElementById("cancelEdit");
let currentNode = null;
let editing = false;

function display(value, suffix = "") {
    return value === null || value === undefined || value === "" ? "Unknown" : `${value}${suffix}`;
}

function escapeHtml(value) {
    const element = document.createElement("span");
    element.textContent = value;
    return element.innerHTML;
}

function rows(items) {
    return items.map(([label, value]) =>
        `<div class="detail-row"><dt>${label}</dt><dd>${value.html ? value.html : escapeHtml(value)}</dd></div>`
    ).join("");
}

function formatUptime(seconds) {
    if (seconds === null || seconds === undefined) return "Unknown";
    let remaining = Math.max(0, Math.floor(seconds));
    const days = Math.floor(remaining / 86400);
    remaining %= 86400;
    const hours = Math.floor(remaining / 3600);
    remaining %= 3600;
    const minutes = Math.floor(remaining / 60);
    const parts = [];
    if (days) parts.push(`${days}d`);
    if (days || hours) parts.push(`${hours}h`);
    parts.push(`${minutes}m`);
    return parts.join(" ");
}

function gpsDisplay(node) {
    return node.latitude === null || node.longitude === null
        ? "Unknown"
        : `${node.latitude}, ${node.longitude}`;
}

function renderNode(node) {
    const statusLabel = node.status.charAt(0).toUpperCase() + node.status.slice(1);
    document.getElementById("nodeHeading").textContent = node.name.trim() || node.node_id;
    document.getElementById("nodeTechnicalId").textContent = node.node_id;
    document.getElementById("nodeInformation").innerHTML = rows([
        ["Name", display(node.name)], ["Category", display(node.category)],
        ["Location", display(node.location)], ["GPS", gpsDisplay(node)],
        ["Enabled", node.enabled ? "Yes" : "No"], ["Node type", display(node.node_type)],
    ]);
    document.getElementById("statusDetails").innerHTML = rows([
        ["Status", {html: `<span class="status-badge status-${node.status}">${escapeHtml(statusLabel)}</span>`}],
        ["Last seen", display(node.last_seen)], ["RSSI", display(node.rssi, " dBm")],
        ["Uptime", formatUptime(node.uptime_seconds)],
    ]);
    document.getElementById("hardwareDetails").innerHTML = rows([
        ["Model", display(node.hardware_model)], ["Revision", display(node.hardware_revision)],
    ]);
    document.getElementById("firmwareDetails").innerHTML = rows([
        ["Name", display(node.firmware_name)], ["Version", display(node.firmware_version)],
        ["OTA hostname", display(node.ota_hostname)],
    ]);
}

function inputRow(label, name, value, type = "text") {
    const checked = type === "checkbox" && value ? " checked" : "";
    const inputValue = type === "checkbox" ? "" : ` value="${escapeHtml(value ?? "")}"`;
    const attributes = type === "number" ? ' step="any"' : "";
    return `<div class="form-row"><label for="${name}">${label}</label><input id="${name}" name="${name}" type="${type}"${inputValue}${checked}${attributes}></div>`;
}

function beginEdit() {
    if (!currentNode) return;
    editing = true;
    document.getElementById("nodeInformation").innerHTML = [
        inputRow("Name", "name", currentNode.name), inputRow("Category", "category", currentNode.category),
        inputRow("Location", "location", currentNode.location), inputRow("Latitude", "latitude", currentNode.latitude, "number"),
        inputRow("Longitude", "longitude", currentNode.longitude, "number"), inputRow("Enabled", "enabled", currentNode.enabled, "checkbox"),
    ].join("");
    editButton.hidden = true;
    saveButton.hidden = false;
    cancelButton.hidden = false;
}

function finishEdit() {
    editing = false;
    editButton.hidden = false;
    saveButton.hidden = true;
    cancelButton.hidden = true;
    renderNode(currentNode);
}

function optionalNumber(name) {
    const value = document.getElementById(name).value.trim();
    return value === "" ? null : Number(value);
}

async function saveNode() {
    const payload = {
        name: document.getElementById("name").value,
        category: document.getElementById("category").value,
        location: document.getElementById("location").value,
        latitude: optionalNumber("latitude"), longitude: optionalNumber("longitude"),
        enabled: document.getElementById("enabled").checked,
    };
    const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`, {
        method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
        document.getElementById("saveMessage").textContent = result.error || "Node could not be saved.";
        return;
    }
    currentNode = result;
    document.getElementById("saveMessage").textContent = "Saved";
    finishEdit();
}

async function loadNodeDetails() {
    try {
        const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`);
        if (!response.ok) throw new Error("Node details request failed");
        const node = await response.json();
        currentNode = node;
        editButton.disabled = false;
        document.getElementById("nodeError").hidden = true;
        if (!editing) renderNode(node);
    } catch (error) {
        document.getElementById("nodeError").hidden = false;
    }
}

editButton.addEventListener("click", beginEdit);
cancelButton.addEventListener("click", finishEdit);
saveButton.addEventListener("click", saveNode);
loadNodeDetails();
setInterval(loadNodeDetails, 5000);
