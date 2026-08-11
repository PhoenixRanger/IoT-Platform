const detailsRoot = document.getElementById("nodeDetails");
const nodeId = detailsRoot.dataset.nodeId;

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

async function loadNodeDetails() {
    const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}`);
    if (!response.ok) {
        document.getElementById("nodeError").hidden = false;
        detailsRoot.hidden = true;
        return;
    }
    const node = await response.json();
    document.getElementById("nodeHeading").textContent = node.name || node.node_id;
    document.getElementById("statusDetails").innerHTML = rows([
        ["Status", {html: `<span class="status-badge status-${node.status}">${escapeHtml(display(node.status))}</span>`}],
        ["Last seen", display(node.last_seen)],
        ["RSSI", display(node.rssi, " dBm")],
        ["Uptime", display(node.uptime_seconds, " s")],
    ]);
    document.getElementById("deviceDetails").innerHTML = rows([
        ["Node ID", display(node.node_id)], ["Name", display(node.name)],
        ["Location", display(node.location)], ["Node type", display(node.node_type)],
        ["Hardware model", display(node.hardware_model)],
        ["Hardware revision", display(node.hardware_revision)],
    ]);
    document.getElementById("firmwareDetails").innerHTML = rows([
        ["Firmware name", display(node.firmware_name)],
        ["Firmware version", display(node.firmware_version)],
        ["OTA hostname", display(node.ota_hostname)],
    ]);
}

loadNodeDetails();
setInterval(loadNodeDetails, 5000);
