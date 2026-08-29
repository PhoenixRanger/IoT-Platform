const FLEET_REFRESH_INTERVAL_MS = 10000;
let fleetNodes = [], groups = [], tags = [], capabilityRegistry = [], hardwarePlatforms = [], componentDefinitions = [], selectionMode = false, currentBulkAction = null, initialUrlFiltersApplied = false;
let activeFilterFamily = null;
const selectedNodeIds = new Set();
const filters = {group: new Set(), tag: new Set(), capability: new Set(), hardware_platform: new Set(), component: new Set(), status: new Set(), health: new Set()};
const filterLabels = {group: "Group", tag: "Tag", capability: "Capability", hardware_platform: "Hardware Platform", component: "Component", status: "Runtime Status", health: "Overall Health"};
const runtimeStatusOptions = ["online", "offline", "unknown", "disabled"];
const overallHealthOptions = ["healthy", "capability_mismatch", "offline", "unknown", "disabled"];

function healthLabel(value) { return value.replaceAll("_", " ").replace(/\b\w/g, character => character.toUpperCase()); }
function matchesSet(selected, values) { return !selected.size || values.some(value => selected.has(String(value))); }
function visibleNodes() {
 const query = document.getElementById("nodeSearch").value.trim().toLocaleLowerCase();
 return fleetNodes.filter(node => (!query || node.node_id.toLocaleLowerCase().includes(query) || node.name.toLocaleLowerCase().includes(query))
  && matchesSet(filters.group, node.groups.map(item => item.id)) && matchesSet(filters.tag, node.tags.map(item => item.id))
  && matchesSet(filters.capability, node.expected_capabilities)
  && matchesSet(filters.hardware_platform, node.hardware_platform ? [node.hardware_platform.hardware_platform_id] : [])
  && matchesSet(filters.component, node.components.map(item => item.definition_key))
  && matchesSet(filters.status, [node.status]) && matchesSet(filters.health, [node.health]));
}
function membershipBlock(items, kind, nodeId) {
 if (!items.length) return document.createTextNode("—");
 const block = document.createElement("div"), first = document.createElement("span"); first.className = kind === "group" ? "group-pill" : "tag-label"; first.textContent = items[0].name; block.append(first);
 if (items.length > 1) { const wrap = document.createElement("span"), trigger = document.createElement("a"), popover = document.createElement("span"); wrap.className = "membership-more"; trigger.href = `/nodes/${encodeURIComponent(nodeId)}#organization`; trigger.textContent = `+${items.length - 1}`; trigger.setAttribute("aria-label", `View all ${kind}s for this node`); popover.className = "membership-popover"; popover.setAttribute("role", "tooltip"); const heading = document.createElement("strong"); heading.textContent = `${kind === "group" ? "Groups" : "Tags"}`; popover.append(heading, ...items.map(item => { const line = document.createElement("span"); line.textContent = item.name; return line; })); wrap.append(trigger, popover); block.append(wrap); }
 return block;
}
function createFleetRow(node) {
 const encodedNodeId = encodeURIComponent(node.node_id);
 const row = document.createElement("tr"), selectionCell = document.createElement("td"), checkbox = document.createElement("input"); selectionCell.className = "selection-column"; selectionCell.hidden = !selectionMode; checkbox.type = "checkbox"; checkbox.checked = selectedNodeIds.has(node.node_id); checkbox.setAttribute("aria-label", `Select ${node.name}`); checkbox.onchange = () => { checkbox.checked ? selectedNodeIds.add(node.node_id) : selectedNodeIds.delete(node.node_id); updateSelectionControls(); }; selectionCell.append(checkbox);
 const identity = document.createElement("td"), name = document.createElement("strong"), id = document.createElement("small"); name.textContent = node.name; id.textContent = node.node_id; identity.append(name, id);
 const groupCell = document.createElement("td"); groupCell.className = "membership-cell group-membership-cell"; groupCell.append(membershipBlock(node.groups, "group", node.node_id));
 const tagCell = document.createElement("td"); tagCell.className = "membership-cell tag-membership-cell"; tagCell.append(membershipBlock(node.tags, "tag", node.node_id));
 const health = document.createElement("td"), indicator = document.createElement("span"); health.className = "fleet-health"; indicator.className = `status-indicator status-indicator-${node.status}`; indicator.setAttribute("aria-hidden", "true"); health.append(indicator, document.createTextNode(healthLabel(node.health)));
 const actions = document.createElement("td"), menuWrap = document.createElement("div"), menuButton = document.createElement("button"), menu = document.createElement("div"); actions.className = "fleet-menu-column"; menuWrap.className = "menu-wrap row-menu-wrap"; menuButton.type = "button"; menuButton.className = "kebab-button"; menuButton.textContent = "⋮"; menuButton.setAttribute("aria-label", `Open actions for ${node.name}`); menuButton.setAttribute("aria-expanded", "false"); menu.className = "action-menu row-action-menu transient-menu"; menu.hidden = true;
 [[`/?node_id=${encodedNodeId}`, "Dashboard"], [`/nodes/${encodedNodeId}`, "Details"], [`/nodes/${encodedNodeId}/technical`, "Technical"]].forEach(([href, text]) => { const link = document.createElement("a"); link.href = href; link.textContent = text; menu.append(link); });
 menuButton.onclick = () => { const opening = menu.hidden; closeTransientMenus(menu); menu.hidden = !opening; menuButton.setAttribute("aria-expanded", String(opening)); row.classList.toggle("menu-open", opening); }; menuWrap.append(menuButton, menu); actions.append(menuWrap); row.append(selectionCell, identity, groupCell, tagCell, health, actions); return row;
}
function reconcileSelection(nodes = visibleNodes()) { const visibleIds = new Set(nodes.map(node => node.node_id)); selectedNodeIds.forEach(nodeId => { if (!visibleIds.has(nodeId)) selectedNodeIds.delete(nodeId); }); }
function updateSelectionControls() { document.querySelectorAll(".selection-column").forEach(item => item.hidden = !selectionMode); document.getElementById("selectionToolbar").hidden = !selectionMode; document.getElementById("toggleSelection").textContent = selectionMode ? "Done" : "Select Nodes"; document.getElementById("selectionCount").textContent = `${selectedNodeIds.size} selected`; }
function renderFleet() { const nodes = visibleNodes(); reconcileSelection(nodes); document.getElementById("fleetRows").replaceChildren(...nodes.map(createFleetRow)); document.getElementById("emptyFleet").hidden = nodes.length !== 0; updateSelectionControls(); }
function filterOptions() { return {group: groups.map(item => [item.id, item.name]), tag: tags.map(item => [item.id, item.name]), capability: capabilityRegistry.map(item => [item.capability_key, item.display_name]), hardware_platform: hardwarePlatforms.map(item => [item.hardware_platform_id, item.display_name]), component: componentDefinitions.map(item => [item.definition_key, item.display_name]), status: runtimeStatusOptions.map(item => [item, healthLabel(item)]), health: overallHealthOptions.map(item => [item, healthLabel(item)])}; }
function renderFilterFamilyMenu(panel) {
 const heading = document.createElement("strong"); heading.className = "filter-panel-heading"; heading.textContent = "Filter Nodes"; panel.append(heading);
 Object.keys(filters).forEach(family => {
  const button = document.createElement("button"); button.type = "button"; button.className = "filter-family-button"; button.textContent = `${filterLabels[family]} ›`; button.onclick = () => { activeFilterFamily = family; renderFilters(); }; panel.append(button);
 });
}
function renderFilterFamilyValues(panel, family) {
 const back = document.createElement("button"); back.type = "button"; back.className = "filter-back-button"; back.textContent = `‹ ${filterLabels[family]}`; back.onclick = () => { activeFilterFamily = null; renderFilters(); }; panel.append(back);
 const options = filterOptions()[family], optionList = document.createElement("div"); optionList.className = "filter-option-list";
 options.forEach(([value, label]) => {
  const wrapper = document.createElement("label"), input = document.createElement("input"); wrapper.dataset.filterLabel = label.toLocaleLowerCase(); input.type = "checkbox"; input.checked = filters[family].has(String(value)); input.onchange = () => { input.checked ? filters[family].add(String(value)) : filters[family].delete(String(value)); syncFilterUrl(); renderActiveFilters(); renderFleet(); }; wrapper.append(input, document.createTextNode(label)); optionList.append(wrapper);
 });
 if (["group", "tag", "capability", "hardware_platform", "component"].includes(family)) {
  const search = document.createElement("input"); search.type = "search"; search.className = "filter-value-search"; search.placeholder = `Search ${family === "capability" ? "capabilities" : `${family}s`}...`; search.setAttribute("aria-label", search.placeholder); search.oninput = () => { const query = search.value.trim().toLocaleLowerCase(); optionList.querySelectorAll("label").forEach(label => { label.hidden = !label.dataset.filterLabel.includes(query); }); }; panel.append(search);
 }
 if (!options.length) { const empty = document.createElement("p"); empty.className = "filter-options-empty"; empty.textContent = `No ${family === "capability" ? "capabilities" : `${family}s`} available.`; optionList.append(empty); }
 panel.append(optionList);
}
function closeTransientMenus(except = null) {
 document.querySelectorAll(".transient-menu").forEach(menu => {
  if (menu === except || menu.hidden) return;
  menu.hidden = true;
  const toggle = menu.previousElementSibling;
  if (toggle) toggle.setAttribute("aria-expanded", "false");
  menu.closest("tr")?.classList.remove("menu-open");
  if (menu.id === "filterPanel") { activeFilterFamily = null; renderFilters(); }
 });
}
function renderFilters() { const panel = document.getElementById("filterPanel"); panel.replaceChildren(); if (activeFilterFamily === null) renderFilterFamilyMenu(panel); else renderFilterFamilyValues(panel, activeFilterFamily); renderActiveFilters(); }
function syncFilterUrl() { const url = new URL(location.href); for (const family of ["hardware_platform", "component"]) { url.searchParams.delete(family); filters[family].forEach(value => url.searchParams.append(family, value)); } history.replaceState(null, "", url); }
function applyUrlFilters() { const options = filterOptions(), params = new URLSearchParams(location.search); for (const family of ["hardware_platform", "component"]) { filters[family].clear(); const valid = new Set(options[family].map(item => String(item[0]))); params.getAll(family).forEach(value => { if (valid.has(value)) filters[family].add(value); }); } }
function renderActiveFilters() { const root = document.getElementById("activeFilters"), options = filterOptions(); root.replaceChildren(); Object.entries(filters).forEach(([family, selected]) => selected.forEach(value => { const found = options[family].find(item => String(item[0]) === value); if (!found) { selected.delete(value); return; } const button = document.createElement("button"); button.className = "filter-chip"; button.textContent = `${filterLabels[family]}: ${found[1]} ×`; button.onclick = () => { selected.delete(value); syncFilterUrl(); renderFilters(); renderFleet(); }; root.append(button); })); if (root.children.length) { const clear = document.createElement("button"); clear.className = "clear-filters"; clear.textContent = "Clear All"; clear.onclick = clearFilters; root.append(clear); } }
function clearFilters() { Object.values(filters).forEach(set => set.clear()); syncFilterUrl(); renderFilters(); renderFleet(); }
async function refreshFleet() { try { const responses = await Promise.all([fetch("/api/nodes/overview"), fetch("/api/groups"), fetch("/api/tags"), fetch("/api/capabilities"), fetch("/api/hardware-platforms"), fetch("/api/components")]); if (responses.some(response => !response.ok)) throw new Error("Fleet request failed"); [fleetNodes, groups, tags, capabilityRegistry, hardwarePlatforms, componentDefinitions] = await Promise.all(responses.map(response => response.json())); if (!initialUrlFiltersApplied) { applyUrlFilters(); initialUrlFiltersApplied = true; } const currentIds = new Set(fleetNodes.map(node => node.node_id)); selectedNodeIds.forEach(id => { if (!currentIds.has(id)) selectedNodeIds.delete(id); }); renderFilters(); renderFleet(); document.getElementById("fleetError").hidden = true; } catch (error) { console.error(error); document.getElementById("fleetError").hidden = false; } }
function openBulk(action) { if (!selectedNodeIds.size) return; currentBulkAction = action; const isGroup = action.endsWith("group"), definitions = isGroup ? groups : tags, title = {"add-group":"Add to Group", "remove-group":"Remove from Group", "add-tag":"Apply Tag", "remove-tag":"Remove Tag"}[action]; document.getElementById("bulkTitle").textContent = title; const choices = document.getElementById("bulkChoices"); choices.replaceChildren(); if (!definitions.length) { const empty = document.createElement("p"); empty.textContent = `No ${isGroup ? "groups" : "tags"} created yet. `; const link = document.createElement("a"); link.href = "/fleet/organization"; link.textContent = "Open Fleet Organization"; empty.append(link); choices.append(empty); } else definitions.forEach(item => { const label = document.createElement("label"), input = document.createElement("input"); input.type = "checkbox"; input.name = "bulkDefinition"; input.value = item.id; label.append(input, document.createTextNode(item.name)); choices.append(label); }); document.getElementById("bulkError").textContent = ""; document.getElementById("bulkDialog").showModal(); }
document.getElementById("bulkForm").onsubmit = async event => { event.preventDefault(); const definition_ids = Array.from(document.querySelectorAll('input[name="bulkDefinition"]:checked'), item => Number(item.value)); if (!definition_ids.length) { document.getElementById("bulkError").textContent = `Select at least one ${currentBulkAction.endsWith("group") ? "group" : "tag"}.`; return; } const response = await fetch("/api/fleet/organization", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({node_ids:Array.from(selectedNodeIds), kind:currentBulkAction.endsWith("group") ? "group" : "tag", definition_ids, operation:currentBulkAction.startsWith("add") ? "add" : "remove"})}); const result = await response.json(); if (!response.ok) { document.getElementById("bulkError").textContent = result.error; return; } document.getElementById("bulkDialog").close(); refreshFleet(); };
document.getElementById("nodeSearch").oninput = renderFleet; document.getElementById("toggleSelection").onclick = () => { if (selectionMode) selectedNodeIds.clear(); selectionMode = !selectionMode; renderFleet(); }; document.getElementById("selectAllNodes").onclick = () => { visibleNodes().forEach(node => selectedNodeIds.add(node.node_id)); renderFleet(); }; document.getElementById("unselectAllNodes").onclick = () => { selectedNodeIds.clear(); renderFleet(); };
document.getElementById("toggleFilters").onclick = event => { const panel = document.getElementById("filterPanel"), opening = panel.hidden; closeTransientMenus(panel); if (opening) { activeFilterFamily = null; renderFilters(); } panel.hidden = !opening; event.currentTarget.setAttribute("aria-expanded", String(opening)); };
document.getElementById("toggleBulkMenu").onclick = event => { const menu = document.getElementById("bulkMenu"), opening = menu.hidden; closeTransientMenus(menu); menu.hidden = !opening; event.currentTarget.setAttribute("aria-expanded", String(opening)); };
document.querySelectorAll("#bulkMenu button").forEach(button => button.onclick = () => { closeTransientMenus(); openBulk(button.dataset.action); }); document.getElementById("clearEmptyFilters").onclick = clearFilters;
document.getElementById("cancelBulk").onclick = () => { document.getElementById("bulkError").textContent = ""; document.getElementById("bulkDialog").close(); };
document.getElementById("filterControl").addEventListener("click", event => event.stopPropagation());
document.addEventListener("click", event => { if (!event.target.closest(".menu-wrap")) closeTransientMenus(); });
document.addEventListener("keydown", event => { if (event.key === "Escape") closeTransientMenus(); });
window.addEventListener("popstate", () => { applyUrlFilters(); renderFilters(); renderFleet(); });
refreshFleet(); setInterval(refreshFleet, FLEET_REFRESH_INTERVAL_MS);
