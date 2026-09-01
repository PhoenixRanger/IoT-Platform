const root = document.getElementById("componentDetailRoot");
const nodeId = root.dataset.nodeId, connectedComponentId = root.dataset.connectedComponentId;
let component = null, mapping = null;
let editingInstance = null;

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
    renderInterfacesSignals();
    const body = document.getElementById("detailCapabilityRows");
    body.replaceChildren();
    component.capability_instances.forEach(capability => {
        const capabilityRow = document.createElement("tr");
        [capability.label, capability.display_name, capability.capability_instance_id,
         human(capability.capability_class), capability.description].forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value;
            capabilityRow.append(cell);
        });
        const actions = document.createElement("td"), menuWrap = document.createElement("div");
        const menuButton = document.createElement("button"), menu = document.createElement("div");
        actions.className = "fleet-menu-column"; menuWrap.className = "menu-wrap row-menu-wrap";
        menuButton.type = "button"; menuButton.className = "kebab-button"; menuButton.textContent = "⋮";
        menuButton.setAttribute("aria-label", `Open actions for ${capability.label}`);
        menuButton.setAttribute("aria-expanded", "false");
        menu.className = "action-menu row-action-menu instance-action-menu"; menu.hidden = true;
        const edit = document.createElement("button"); edit.type = "button"; edit.textContent = "Edit";
        edit.onclick = () => openInstanceEditor(capability);
        menuButton.onclick = event => { event.stopPropagation(); closeInstanceMenus(menu); const opening = menu.hidden;
            menu.hidden = !opening; menuButton.setAttribute("aria-expanded", String(opening)); capabilityRow.classList.toggle("menu-open", opening); };
        menu.append(edit); menuWrap.append(menuButton, menu); actions.append(menuWrap); capabilityRow.append(actions);
        body.append(capabilityRow);
    });
}

function closeInstanceMenus(except = null) {
    document.querySelectorAll(".instance-action-menu").forEach(menu => {
        if (menu === except) return;
        menu.hidden = true; menu.previousElementSibling?.setAttribute("aria-expanded", "false");
        menu.closest("tr")?.classList.remove("menu-open");
    });
}

function openInstanceEditor(instance) {
    closeInstanceMenus(); editingInstance = instance;
    document.getElementById("instanceIdentity").replaceChildren(
        row("Capability", instance.display_name), row("Instance ID", instance.capability_instance_id),
        row("Connected Component", component.connected_component_id), row("Node", component.node_id));
    document.getElementById("instanceLabel").value = instance.label;
    document.getElementById("editInstanceError").textContent = "";
    document.getElementById("editInstanceDialog").showModal();
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
    const mappingResponse = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(connectedComponentId)}/hardware-mapping`);
    mapping = await mappingResponse.json();
    render();
    document.getElementById("editComponent").disabled = component.lifecycle_status !== "active";
    document.getElementById("detailError").hidden = true;
}

document.getElementById("editComponent").onclick = openEditor;
document.addEventListener("click", event => { if (!event.target.closest(".row-menu-wrap")) closeInstanceMenus(); });
document.getElementById("cancelEditInstance").onclick = () => {
    document.getElementById("editInstanceDialog").close(); editingInstance = null;
};
document.getElementById("editInstanceForm").onsubmit = async event => {
    event.preventDefault();
    const response = await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/capability-instances/${encodeURIComponent(editingInstance.capability_instance_id)}`,
        {method: "PATCH", headers: {"Content-Type": "application/json"},
         body: JSON.stringify({label: document.getElementById("instanceLabel").value})});
    const result = await response.json();
    if (!response.ok) { document.getElementById("editInstanceError").textContent = result.error; return; }
    editingInstance.label = result.label; render(); document.getElementById("editInstanceDialog").close(); editingInstance = null;
};
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


function renderInterfacesSignals() {
    const interfaces = document.getElementById("interfaceList");
    const state = document.createElement("span");
    interfaces.replaceChildren();
    state.className = `mapping-state ${mappingStateClass(mapping?.mapping_state)}`;
    state.textContent = mapping?.mapping_state === "Mapped"
        ? "✓ Mapped" : (mapping?.mapping_state || "Unmapped");
    interfaces.append(state);
    (mapping?.interfaces_signals || []).forEach(item => {
        const block = document.createElement("div");
        const title = document.createElement("strong");
        block.className = "mapping-summary";
        title.textContent = item.kind === "protocol"
            ? item.interface_label : item.endpoint_label;
        block.append(title);
        (item.endpoints || [item]).forEach(endpoint => {
            block.append(row(
                endpoint.endpoint_label,
                endpoint.mapped_resource?.resource || "Unmapped"
            ));
        });
        if (item.protocol === "i2c") {
            block.append(row("I²C Address", item.selected_i2c_address || "Unmapped"));
        }
        interfaces.append(block);
    });
}

function mappingStateClass(value) {
    return {
        Mapped: "state-success",
        Complete: "state-success",
        "Partially Mapped": "state-warning",
        Incomplete: "state-warning",
        Unmapped: "state-danger",
        Invalid: "state-danger",
    }[value] || "state-danger";
}

function resourceOptionLabel(resource) {
    if (resource.occupancy_state === "Free") return `${resource.resource} — Free`;
    const roles = resource.occupancy_roles.join(" · ");
    return `${resource.resource} — Shared · ${roles}`;
}

function endpointMappingField(endpoint) {
    const label = document.createElement("label");
    const select = document.createElement("select");
    label.append(document.createTextNode(endpoint.endpoint_label));
    select.dataset.endpointId = endpoint.endpoint_id;
    select.add(new Option("Not mapped", ""));
    endpoint.eligible_resources.forEach(resource => {
        select.add(new Option(resourceOptionLabel(resource), resource.resource_id));
    });
    select.value = endpoint.mapped_resource?.resource_id || "";
    label.append(select);
    return label;
}

function i2cAddressField(item) {
    const label = document.createElement("label");
    const input = item.i2c_address_options.length
        ? document.createElement("select") : document.createElement("input");
    label.append(document.createTextNode("I²C Address"));
    input.dataset.i2cKey = item.interface_key;
    if (item.i2c_address_options.length) {
        input.add(new Option("Not configured", ""));
        item.i2c_address_options.forEach(address => {
            input.add(new Option(address, address));
        });
    } else {
        input.placeholder = "0x__";
    }
    input.value = item.selected_i2c_address || "";
    label.append(input);
    return label;
}

function mappingSection(item) {
    const section = document.createElement("fieldset");
    const legend = document.createElement("legend");
    legend.textContent = item.kind === "protocol" ? item.interface_label : "Direct Signals";
    section.append(legend);
    (item.endpoints || [item]).forEach(endpoint => {
        section.append(endpointMappingField(endpoint));
    });
    if (item.protocol === "i2c") section.append(i2cAddressField(item));
    return section;
}

function openMappingEditor() {
    const title = document.getElementById("mappingTitle");
    const fields = document.getElementById("mappingFields");
    const error = document.getElementById("mappingError");
    title.textContent = `Edit Hardware Mapping — ${component.label}`;
    fields.replaceChildren();
    error.textContent = "";
    if (!mapping.hardware_platform_id) {
        error.textContent = "Assign a Hardware Platform to this Node before mapping.";
        document.getElementById("mappingDialog").showModal();
        return;
    }
    mapping.interfaces_signals.forEach(item => fields.append(mappingSection(item)));
    document.getElementById("mappingDialog").showModal();
}

function proposedMappingPayload() {
    const fields = document.getElementById("mappingFields");
    const mappings = Array.from(fields.querySelectorAll("[data-endpoint-id]"))
        .filter(select => select.value)
        .map(select => ({
            endpoint_id: Number(select.dataset.endpointId),
            resource_id: Number(select.value),
        }));
    const i2cAddresses = Object.fromEntries(
        Array.from(fields.querySelectorAll("[data-i2c-key]"))
            .filter(input => input.value.trim())
            .map(input => [input.dataset.i2cKey, input.value])
    );
    return {mappings, i2c_addresses: i2cAddresses};
}

document.getElementById("editMapping").onclick = openMappingEditor;
document.getElementById("cancelMapping").onclick = () => {
    document.getElementById("mappingError").textContent = "";
    document.getElementById("mappingDialog").close();
};
document.getElementById("mappingForm").onsubmit = async event => {
    event.preventDefault();
    const response = await fetch(
        `/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(connectedComponentId)}/hardware-mapping`,
        {
            method: "PUT",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(proposedMappingPayload()),
        }
    );
    const result = await response.json();
    if (!response.ok) {
        document.getElementById("mappingError").textContent = (
            result.validation_errors || []
        ).map(error => error.message).join(" · ") || result.error;
        return;
    }
    mapping = result;
    render();
    document.getElementById("mappingDialog").close();
};
