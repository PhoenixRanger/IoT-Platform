const root = document.getElementById("componentDetailRoot");
const nodeId = root.dataset.nodeId, connectedComponentId = root.dataset.connectedComponentId;
let component = null;

function row(label, value) {
    const wrapper = document.createElement("div"), term = document.createElement("dt");
    const detail = document.createElement("dd");
    wrapper.className = "detail-row";
    term.textContent = label;
    detail.textContent = value || "—";
    wrapper.append(term, detail);
    return wrapper;
}

function human(value) {
    return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function render() {
    document.getElementById("componentHeading").textContent = component.label;
    document.getElementById("nodeDetails").replaceChildren(
        row("Node", component.node_name),
        row("Node ID", component.node_id),
        row("Location", component.location),
        row("Zone", component.zone),
        row("Added", component.created_at)
    );
    document.getElementById("componentDetails").replaceChildren(
        row("Component", component.display_name),
        row("Component ID", component.connected_component_id),
        row("Manufacturer", component.manufacturer),
        row("Model", component.model),
        row("Class", human(component.component_class))
    );
    const interfaces = document.getElementById("interfaceList");
    interfaces.replaceChildren(...component.interfaces.map(value => {
        const item = document.createElement("li");
        item.textContent = human(value);
        return item;
    }));
    const body = document.getElementById("detailCapabilityRows");
    body.replaceChildren();
    component.capability_instances.forEach(capability => {
        const capabilityRow = document.createElement("tr");
        [capability.display_name, capability.capability_instance_id,
         human(capability.capability_class), capability.description].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value;
            capabilityRow.append(cell);
        });
        body.append(capabilityRow);
    });
}

function openEditor() {
    document.getElementById("editComponentIdentity").textContent =
        component.display_name;
    document.getElementById("detailComponentLabel").value = component.label;
    document.getElementById("detailComponentLocation").value = component.location || "";
    document.getElementById("detailComponentZone").value = component.zone || "";
    document.getElementById("editComponentError").textContent = "";
    document.getElementById("editComponentDialog").showModal();
}

async function load() {
    const response = await fetch(
        `/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(connectedComponentId)}`
    );
    if (!response.ok) throw new Error();
    component = await response.json();
    render();
    document.getElementById("editComponent").disabled = component.lifecycle_status !== "active";
    document.getElementById("detailError").hidden = true;
}

document.getElementById("editComponent").onclick = openEditor;
document.getElementById("cancelEditComponent").onclick = () => {
    document.getElementById("editComponentError").textContent = "";
    document.getElementById("editComponentDialog").close();
};
document.getElementById("editComponentForm").onsubmit = async event => {
    event.preventDefault();
    const response = await fetch(
        `/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(connectedComponentId)}`,
        {
            method: "PATCH",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                label: document.getElementById("detailComponentLabel").value,
                location: document.getElementById("detailComponentLocation").value || null,
                zone: document.getElementById("detailComponentZone").value || null,
            }),
        }
    );
    const result = await response.json();
    if (!response.ok) {
        document.getElementById("editComponentError").textContent = result.error;
        return;
    }
    component = result;
    render();
    document.getElementById("editComponentDialog").close();
};
load().catch(() => document.getElementById("detailError").hidden = false);
