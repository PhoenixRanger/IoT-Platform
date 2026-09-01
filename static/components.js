const protocolEndpoints = {
    i2c: ["sda", "scl"],
    uart: ["tx", "rx"],
    spi: ["mosi", "miso", "sck", "cs"],
};
const directSignalTypes = [
    ["analog_input", "ADC — Analog Input to Node"],
    ["analog_output", "DAC — Analog Output from Node"],
    ["digital_input", "Digital Input — Input to Node"],
    ["digital_output", "Digital Output — Output from Node"],
    ["digital_io", "Digital I/O — Bidirectional"],
    ["pwm_output", "PWM — Output from Node"],
];
const compactDirectSignalTypes = {
    analog_input: "ADC",
    analog_output: "DAC",
    digital_input: "Digital Input",
    digital_output: "Digital Output",
    digital_io: "Digital I/O",
    pwm_output: "PWM",
};

let definitions = [];
let capabilities = [];
let editingKey = null;
let deletingDefinition = null;
let interfacesSignals = [];
let technicalLocked = false;

function human(value) {
    return value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());
}

function capabilityChoices(selected = []) {
    const root = document.getElementById("capabilityChoices");
    root.replaceChildren();
    capabilities.forEach(capability => {
        const label = document.createElement("label");
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "capabilities";
        input.value = capability.capability_key;
        input.checked = selected.includes(input.value);
        label.append(input, document.createTextNode(capability.display_name));
        root.append(label);
    });
}

function interfacesSummary(item) {
    return item.interfaces_signals.map(interfaceSignal => {
        if (interfaceSignal.kind === "protocol") return interfaceSignal.interface_label;
        const type = compactDirectSignalTypes[interfaceSignal.signal_type] || "Direct Signal";
        return `${type}: ${interfaceSignal.endpoint_label}`;
    }).join(" | ") || "—";
}

function closeRowMenus(except = null) {
    document.querySelectorAll(".component-action-menu").forEach(menu => {
        if (menu === except || menu.hidden) return;
        menu.hidden = true;
        menu.previousElementSibling?.setAttribute("aria-expanded", "false");
        menu.closest("tr")?.classList.remove("menu-open");
    });
}

function render() {
    const body = document.getElementById("componentRows");
    body.replaceChildren();
    definitions.forEach(item => {
        const tr = document.createElement("tr");
        const values = [
            item.display_name,
            human(item.component_class),
            [item.manufacturer, item.model].filter(Boolean).join(" · ") || "—",
            interfacesSummary(item),
            item.capabilities.map(capability => capability.display_name).join(" · ") || "—",
        ];
        values.forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value;
            tr.append(cell);
        });

        const usage = document.createElement("td");
        const usageLink = document.createElement("a");
        usageLink.className = "usage-count-link";
        usageLink.href = `/nodes?component=${encodeURIComponent(item.definition_key)}`;
        usageLink.textContent = String(item.active_node_count);
        usage.append(usageLink);
        tr.append(usage);

        const actions = document.createElement("td");
        const wrap = document.createElement("div");
        const trigger = document.createElement("button");
        const menu = document.createElement("div");
        actions.className = "fleet-menu-column";
        wrap.className = "menu-wrap row-menu-wrap";
        trigger.type = "button";
        trigger.className = "kebab-button";
        trigger.textContent = "⋮";
        trigger.setAttribute("aria-label", `Actions for ${item.display_name}`);
        trigger.setAttribute("aria-expanded", "false");
        menu.className = "action-menu row-action-menu component-action-menu";
        menu.hidden = true;
        [["Edit", () => openForm(item)], ["Delete", () => deleteDefinition(item)]].forEach(
            ([text, action]) => {
                const button = document.createElement("button");
                button.type = "button";
                button.textContent = text;
                button.onclick = () => {
                    closeRowMenus();
                    action();
                };
                menu.append(button);
            }
        );
        trigger.onclick = () => {
            const opening = menu.hidden;
            closeRowMenus(menu);
            menu.hidden = !opening;
            trigger.setAttribute("aria-expanded", String(opening));
            tr.classList.toggle("menu-open", opening);
        };
        wrap.append(trigger, menu);
        actions.append(wrap);
        tr.append(actions);
        body.append(tr);
    });
    if (!definitions.length) {
        body.innerHTML = '<tr><td colspan="7" class="fleet-empty">No component definitions.</td></tr>';
    }
}

function editableStructure(item) {
    if (item.kind === "protocol") {
        return {
            kind: "protocol",
            protocol: item.protocol,
            interface_key: item.interface_key,
            endpoints: item.endpoints.map(endpoint => endpoint.endpoint_key),
            i2c_address_options: [...item.i2c_address_options],
        };
    }
    return {
        kind: "direct_signal",
        signal_type: item.signal_type,
        endpoint_key: item.endpoint_key,
        endpoint_label: item.endpoint_label,
        optional: !item.required,
    };
}

function generatedInterfaceKey(protocol, throughIndex) {
    const number = interfacesSignals.slice(0, throughIndex + 1).filter(
        item => item.kind === "protocol" && item.protocol === protocol
    ).length;
    return `${protocol}-${number}`;
}

function labeledInput(labelText, input) {
    const label = document.createElement("label");
    label.append(document.createTextNode(labelText), input);
    return label;
}

function removeButton(index) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "danger-link";
    button.textContent = "Remove";
    button.onclick = () => {
        interfacesSignals.splice(index, 1);
        renderInterfacesSignals();
    };
    return button;
}

function renderEndpointChoices(block, item) {
    const choices = document.createElement("div");
    choices.className = "endpoint-choices";
    protocolEndpoints[item.protocol].forEach(endpointKey => {
        const input = document.createElement("input");
        const label = document.createElement("label");
        input.type = "checkbox";
        input.checked = item.endpoints.includes(endpointKey);
        input.disabled = technicalLocked || item.protocol === "i2c";
        input.onchange = () => {
            item.endpoints = input.checked
                ? [...item.endpoints, endpointKey]
                : item.endpoints.filter(value => value !== endpointKey);
        };
        label.append(input, document.createTextNode(endpointKey.toUpperCase()));
        choices.append(label);
    });
    block.append(choices);
}

function renderAddressOptions(block, item) {
    if (item.protocol !== "i2c") return;
    const addresses = document.createElement("div");
    const heading = document.createElement("strong");
    addresses.className = "addresses";
    heading.textContent = "I²C Address Options";
    addresses.append(heading);
    item.i2c_address_options.forEach((address, index) => {
        const input = document.createElement("input");
        input.value = address;
        input.disabled = technicalLocked;
        input.setAttribute("aria-label", `I²C address option ${index + 1}`);
        input.oninput = () => { item.i2c_address_options[index] = input.value; };
        addresses.append(input);
        if (!technicalLocked) {
            const remove = document.createElement("button");
            remove.type = "button";
            remove.textContent = "×";
            remove.setAttribute("aria-label", `Remove ${address || "address option"}`);
            remove.onclick = () => {
                item.i2c_address_options.splice(index, 1);
                renderInterfacesSignals();
            };
            addresses.append(remove);
        }
    });
    if (!technicalLocked) {
        const add = document.createElement("button");
        add.type = "button";
        add.textContent = "+ Add Address";
        add.onclick = () => {
            item.i2c_address_options.push("0x");
            renderInterfacesSignals();
        };
        addresses.append(add);
    }
    block.append(addresses);
}

function renderProtocolBlock(item, index) {
    item.interface_key = generatedInterfaceKey(item.protocol, index);
    const block = document.createElement("div");
    const fields = document.createElement("div");
    const protocol = document.createElement("select");
    const interfaceName = document.createElement("input");
    block.className = "interface-signal-block";
    fields.className = "form-row";
    [["i2c", "I²C"], ["spi", "SPI"], ["uart", "UART"]].forEach(
        ([value, label]) => protocol.add(new Option(label, value))
    );
    protocol.value = item.protocol;
    protocol.disabled = technicalLocked;
    protocol.onchange = () => {
        item.protocol = protocol.value;
        item.endpoints = [...protocolEndpoints[item.protocol]];
        item.i2c_address_options = [];
        renderInterfacesSignals();
    };
    interfaceName.value = item.interface_key.toUpperCase().replace("I2C", "I²C");
    interfaceName.readOnly = true;
    fields.append(labeledInput("Protocol", protocol), labeledInput("Interface", interfaceName));
    block.append(fields);
    renderEndpointChoices(block, item);
    renderAddressOptions(block, item);
    if (!technicalLocked) block.append(removeButton(index));
    return block;
}

function renderDirectSignalBlock(item, index) {
    const block = document.createElement("div");
    const fields = document.createElement("div");
    const signalType = document.createElement("select");
    const endpointLabel = document.createElement("input");
    const optionalLabel = document.createElement("label");
    const optional = document.createElement("input");
    block.className = "interface-signal-block";
    fields.className = "form-row";
    directSignalTypes.forEach(([value, label]) => signalType.add(new Option(label, value)));
    signalType.value = item.signal_type;
    signalType.disabled = technicalLocked;
    signalType.onchange = () => { item.signal_type = signalType.value; };
    endpointLabel.value = item.endpoint_label;
    endpointLabel.required = true;
    endpointLabel.disabled = technicalLocked;
    endpointLabel.oninput = () => { item.endpoint_label = endpointLabel.value; };
    optional.type = "checkbox";
    optional.checked = item.optional;
    optional.disabled = technicalLocked;
    optional.onchange = () => { item.optional = optional.checked; };
    optionalLabel.append(optional, document.createTextNode(" Optional signal"));
    fields.append(
        labeledInput("Signal type", signalType),
        labeledInput("Endpoint label", endpointLabel)
    );
    block.append(fields, optionalLabel);
    if (!technicalLocked) block.append(removeButton(index));
    return block;
}

function renderInterfacesSignals() {
    const root = document.getElementById("interfaceSignalBlocks");
    root.replaceChildren();
    interfacesSignals.forEach((item, index) => {
        root.append(item.kind === "protocol"
            ? renderProtocolBlock(item, index)
            : renderDirectSignalBlock(item, index));
    });
}

function openForm(item = null) {
    closeRowMenus();
    editingKey = item?.definition_key || null;
    technicalLocked = Boolean(item?.technical_locked);
    interfacesSignals = (item?.interfaces_signals || []).map(editableStructure);
    document.getElementById("componentDialogTitle").textContent = item
        ? "Edit Component Definition" : "Create Component";
    document.getElementById("componentName").value = item?.display_name || "";
    document.getElementById("manufacturer").value = item?.manufacturer || "";
    document.getElementById("model").value = item?.model || "";
    document.getElementById("componentClass").value = item?.component_class || "sensor";
    document.getElementById("componentClass").disabled = technicalLocked;
    document.getElementById("technicalLockMessage").hidden = !technicalLocked;
    document.getElementById("interfaceSignalActions").hidden = technicalLocked;
    document.getElementById("formError").textContent = "";
    capabilityChoices(item?.capabilities.map(capability => capability.capability_key));
    renderInterfacesSignals();
    document.getElementById("componentDialog").showModal();
}

function deleteDefinition(item) {
    closeRowMenus();
    deletingDefinition = item;
    document.getElementById("deleteComponentTitle").textContent = `Delete “${item.display_name}”?`;
    document.getElementById("deleteComponentError").textContent = "";
    document.getElementById("deleteComponentDialog").showModal();
}

document.getElementById("addProtocol").onclick = () => {
    interfacesSignals.push({
        kind: "protocol", protocol: "i2c", endpoints: ["sda", "scl"],
        i2c_address_options: [],
    });
    renderInterfacesSignals();
};
document.getElementById("addDirectSignal").onclick = () => {
    interfacesSignals.push({
        kind: "direct_signal", signal_type: "digital_input",
        endpoint_label: "", optional: false,
    });
    renderInterfacesSignals();
};

document.getElementById("deleteComponentForm").onsubmit = async event => {
    event.preventDefault();
    const response = await fetch(
        `/api/components/${encodeURIComponent(deletingDefinition.definition_key)}`,
        {method: "DELETE"}
    );
    const result = await response.json();
    if (!response.ok) {
        document.getElementById("deleteComponentError").textContent = result.error;
        return;
    }
    document.getElementById("deleteComponentDialog").close();
    load();
};

document.getElementById("componentForm").onsubmit = async event => {
    event.preventDefault();
    const payload = {
        display_name: document.getElementById("componentName").value,
        manufacturer: document.getElementById("manufacturer").value || null,
        model: document.getElementById("model").value || null,
        capabilities: Array.from(
            document.querySelectorAll('[name="capabilities"]:checked'), item => item.value
        ),
    };
    if (!technicalLocked) {
        payload.component_class = document.getElementById("componentClass").value;
        payload.interfaces_signals = interfacesSignals;
    }
    const response = await fetch(
        editingKey ? `/api/components/${encodeURIComponent(editingKey)}` : "/api/components",
        {
            method: editingKey ? "PATCH" : "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload),
        }
    );
    const result = await response.json();
    if (!response.ok) {
        document.getElementById("formError").textContent = result.error;
        return;
    }
    document.getElementById("componentDialog").close();
    load();
};

document.getElementById("createComponent").onclick = () => openForm();
document.getElementById("cancelComponent").onclick = () => {
    document.getElementById("formError").textContent = "";
    document.getElementById("componentDialog").close();
};
document.getElementById("cancelDeleteComponent").onclick = () => {
    document.getElementById("deleteComponentError").textContent = "";
    document.getElementById("deleteComponentDialog").close();
};
document.addEventListener("click", event => {
    if (!event.target.closest(".row-menu-wrap")) closeRowMenus();
});
document.addEventListener("keydown", event => {
    if (event.key === "Escape") closeRowMenus();
});

async function load() {
    const responses = await Promise.all([fetch("/api/components"), fetch("/api/capabilities")]);
    [definitions, capabilities] = await Promise.all(responses.map(response => response.json()));
    capabilities = capabilities.filter(
        capability => capability.capability_class !== "communication"
    );
    render();
}
load();
