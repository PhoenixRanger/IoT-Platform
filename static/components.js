const interfaces = ["i2c", "spi", "uart", "analog_signal", "digital_signal"];
let definitions = [], capabilities = [], editingKey = null, deletingDefinition = null;
const human = value => value.replaceAll("_", " ").replace(/\b\w/g, letter => letter.toUpperCase());

function choices(root, values, name, selected = []) {
    root.replaceChildren();
    values.forEach(value => {
        const label = document.createElement("label"), input = document.createElement("input");
        input.type = "checkbox";
        input.name = name;
        input.value = typeof value === "string" ? value : value.capability_key;
        input.checked = selected.includes(input.value);
        label.append(input, document.createTextNode(
            typeof value === "string" ? human(value) : value.display_name
        ));
        root.append(label);
    });
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
            item.interfaces.map(human).join(" · ") || "—",
            item.capabilities.map(capability => capability.display_name).join(" · ") || "—",
        ];
        values.forEach(value => {
            const cell = document.createElement("td");
            cell.textContent = value;
            tr.append(cell);
        });
        const usage = document.createElement("td"), usageLink = document.createElement("a");
        usageLink.className = "usage-count-link";
        usageLink.href = `/nodes?component=${encodeURIComponent(item.definition_key)}`;
        usageLink.textContent = String(item.active_node_count);
        usage.append(usageLink);
        tr.append(usage);

        const actions = document.createElement("td"), wrap = document.createElement("div");
        const trigger = document.createElement("button"), menu = document.createElement("div");
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

function openForm(item = null) {
    closeRowMenus();
    editingKey = item?.definition_key || null;
    document.getElementById("componentDialogTitle").textContent = item ? "Edit Component Definition" : "Create Component";
    document.getElementById("componentName").value = item?.display_name || "";
    document.getElementById("manufacturer").value = item?.manufacturer || "";
    document.getElementById("model").value = item?.model || "";
    document.getElementById("componentClass").value = item?.component_class || "sensor";
    choices(document.getElementById("interfaceChoices"), interfaces, "interfaces", item?.interfaces);
    choices(document.getElementById("capabilityChoices"), capabilities, "capabilities", item?.capabilities.map(capability => capability.capability_key));
    document.getElementById("formError").textContent = "";
    document.getElementById("componentDialog").showModal();
}

function deleteDefinition(item) {
    closeRowMenus();
    deletingDefinition = item;
    document.getElementById("deleteComponentTitle").textContent = `Delete “${item.display_name}”?`;
    document.getElementById("deleteComponentError").textContent = "";
    document.getElementById("deleteComponentDialog").showModal();
}

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
        component_class: document.getElementById("componentClass").value,
        interfaces: Array.from(document.querySelectorAll('[name="interfaces"]:checked'), item => item.value),
        capabilities: Array.from(document.querySelectorAll('[name="capabilities"]:checked'), item => item.value),
    };
    const response = await fetch(
        editingKey ? `/api/components/${encodeURIComponent(editingKey)}` : "/api/components",
        {method: editingKey ? "PATCH" : "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)}
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
document.getElementById("cancelComponent").onclick = () => document.getElementById("componentDialog").close();
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
    capabilities = capabilities.filter(capability => capability.capability_class !== "communication");
    render();
}
load();
