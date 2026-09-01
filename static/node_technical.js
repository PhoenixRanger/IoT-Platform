const root=document.getElementById("technicalRoot"),nodeId=root.dataset.nodeId;let node=null,definitions=[],connectedComponents=[],editingComponent=null,removingComponent=null,allocation=null,allocationFilter="all";
function display(value,suffix=""){return value===null||value===undefined||value===""?"Unknown":`${value}${suffix}`;} function row(label,value){const wrapper=document.createElement("div"),term=document.createElement("dt"),detail=document.createElement("dd");wrapper.className="detail-row";term.textContent=label;detail.textContent=value;wrapper.append(term,detail);return wrapper;}
function capabilityList(items,empty,{counts=false,checks=false}={}){const wrapper=document.createElement("div");if(!items.length){wrapper.className="capability-empty";wrapper.textContent=empty;return wrapper;}const list=document.createElement("ul");list.className="capability-list";items.forEach(item=>{const entry=document.createElement("li");entry.textContent=`${checks?"✓ ":""}${item.display_name}${counts&&item.count>1?`  ${item.count}×`:""}`;list.append(entry);});wrapper.append(list);return wrapper;}
function renderCapabilities(){const target=document.getElementById("capabilityDetails");target.replaceChildren();[["Expected",node.capabilities.expected,"None",{counts:true}],["Reported",node.capabilities.reported,node.capabilities.reported_at?"None":"Not reported",{checks:true}],["Missing",node.capabilities.missing,"None",{}],["Additional / Unexpected",node.capabilities.unexpected,"None",{}]].forEach(([heading,items,empty,options])=>{const title=document.createElement("h3");title.textContent=heading;target.append(title,capabilityList(items,empty,options));});target.append(row("Capability State",display(node.capabilities.state)),row("Reported at",display(node.capabilities.reported_at)));}
function closeComponentMenus(except=null){document.querySelectorAll(".component-action-menu").forEach(menu=>{if(menu===except||menu.hidden)return;menu.hidden=true;menu.previousElementSibling?.setAttribute("aria-expanded","false");menu.closest("tr")?.classList.remove("menu-open");});}
const compactDirectSignalTypes={analog_input:"ADC",analog_output:"DAC",digital_input:"Digital Input",digital_output:"Digital Output",digital_io:"Digital I/O",pwm_output:"PWM"};
const mappingStateClasses={Mapped:"state-success",Complete:"state-success","Partially Mapped":"state-warning",Incomplete:"state-warning",Unmapped:"state-danger",Invalid:"state-danger"};
function mappingStateClass(value){return mappingStateClasses[value]||"state-danger";}
function interfacesSignalsSummary(item){return item.interfaces_signals.map(entry=>{if(entry.kind==="protocol")return entry.interface_label;const type=compactDirectSignalTypes[entry.signal_type]||"Direct Signal";return `${type}: ${entry.endpoint_label}`;}).join(" | ")||"—";}
function renderComponents(){
    const body=document.getElementById("nodeComponentRows");
    body.replaceChildren();
    connectedComponents.forEach(item=>{
        const tr=document.createElement("tr"),label=document.createElement("td");
        const labelText=document.createElement("strong");
        labelText.textContent=item.label;
        label.append(labelText);
        tr.append(label);
        [item.display_name,interfacesSignalsSummary(item),item.capabilities.map(cap=>cap.display_name).join(" · ")||"—",item.location||"—",item.zone||"—"].forEach(value=>{
            const td=document.createElement("td");
            td.textContent=value;
            tr.append(td);
        });
        const mappingCell=document.createElement("td");
        mappingCell.className=mappingStateClass(item.mapping_state);
        mappingCell.textContent=item.mapping_state==="Mapped"?"✓ Mapped":item.mapping_state;
        tr.append(mappingCell);
        const actions=document.createElement("td"),wrap=document.createElement("div"),button=document.createElement("button"),menu=document.createElement("div");
        wrap.className="menu-wrap row-menu-wrap";
        button.type="button";
        button.className="kebab-button";
        button.setAttribute("aria-label",`Actions for ${item.label}`);
        button.setAttribute("aria-expanded","false");
        button.textContent="⋮";
        menu.className="action-menu row-action-menu component-action-menu";
        menu.hidden=true;
        [["View Details / Open",()=>location.href=`/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(item.connected_component_id)}`],["Edit",()=>openComponent(item)],["Remove",()=>openRemove(item)]].forEach(([text,action])=>{
            const option=document.createElement("button");
            option.type="button";
            option.textContent=text;
            option.onclick=()=>{closeComponentMenus();action();};
            menu.append(option);
        });
        button.onclick=()=>{const opening=menu.hidden;closeComponentMenus(menu);menu.hidden=!opening;button.setAttribute("aria-expanded",String(opening));tr.classList.toggle("menu-open",opening);};
        wrap.append(button,menu);
        actions.className="fleet-menu-column";
        actions.append(wrap);
        tr.append(actions);
        body.append(tr);
    });
    if(!connectedComponents.length)body.innerHTML='<tr><td colspan="8" class="fleet-empty">No active components. Add an existing Component Library definition.</td></tr>';
}
function render(){document.getElementById("nodeHeading").textContent=`${node.name} — Technical`;document.getElementById("nodeTechnicalId").textContent=node.node_id;document.getElementById("statusDetails").replaceChildren(row("Status",display(node.status)),row("Overall health",display(node.health)),row("Last seen",display(node.last_seen)),row("RSSI",display(node.rssi," dBm")),row("Uptime seconds",display(node.uptime_seconds)));document.getElementById("hardwareDetails").replaceChildren(row("Node type",display(node.node_type)),row("Hardware Platform",display(node.hardware_platform?.display_name)),row("Manufacturer",display(node.hardware_platform?.manufacturer)),row("Model",display(node.hardware_platform?.model)),row("MCU",display(node.hardware_platform?.mcu)),row("Revision",display(node.hardware_platform?.revision)));document.getElementById("firmwareDetails").replaceChildren(row("Name",display(node.firmware_name)),row("Version",display(node.firmware_version)),row("OTA hostname",display(node.ota_hostname)));renderCapabilities();renderComponents();renderAllocation();}
function showPreview(){const item=definitions.find(x=>x.definition_key===document.getElementById("componentDefinition").value),preview=document.getElementById("definitionPreview");preview.textContent=item?`${item.display_name} · ${item.interfaces.map(x=>x.replaceAll("_"," ")).join(", ")||"No interface"} · ${item.capabilities.map(x=>x.display_name).join(", ")||"No capabilities"}`:"";}
function openComponent(item=null){editingComponent=item;const select=document.getElementById("componentDefinition");select.replaceChildren();definitions.forEach(def=>{const option=document.createElement("option");option.value=def.definition_key;option.textContent=def.display_name;select.append(option);});document.getElementById("connectedComponentDialogTitle").textContent=item?"Edit Component":"Add Component";select.disabled=!!item;select.value=item?.definition_key||definitions[0]?.definition_key||"";document.getElementById("connectedComponentLabel").value=item?.label||"";document.getElementById("connectedComponentLocation").value=item?.location??node.location??"";document.getElementById("connectedComponentZone").value=item?.zone||"";document.getElementById("connectedComponentError").textContent="";showPreview();document.getElementById("connectedComponentDialog").showModal();}
function openRemove(item){removingComponent=item;document.getElementById("removeError").textContent="";document.getElementById("removeDialog").showModal();}
async function refresh(){const responses=await Promise.all([fetch(`/api/nodes/${encodeURIComponent(nodeId)}`),fetch("/api/components"),fetch(`/api/nodes/${encodeURIComponent(nodeId)}/components`),fetch(`/api/nodes/${encodeURIComponent(nodeId)}/hardware-allocation`)]);if(responses.some(x=>!x.ok))throw new Error();[node,definitions,connectedComponents,allocation]=await Promise.all(responses.map(x=>x.json()));render();}
document.getElementById("componentDefinition").onchange=showPreview;document.getElementById("addComponent").onclick=()=>openComponent();document.getElementById("cancelConnectedComponent").onclick=()=>document.getElementById("connectedComponentDialog").close();document.getElementById("connectedComponentForm").onsubmit=async event=>{event.preventDefault();const payload={label:document.getElementById("connectedComponentLabel").value,location:document.getElementById("connectedComponentLocation").value||null,zone:document.getElementById("connectedComponentZone").value||null};if(!editingComponent)payload.definition_key=document.getElementById("componentDefinition").value;const url=editingComponent?`/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(editingComponent.connected_component_id)}`:`/api/nodes/${encodeURIComponent(nodeId)}/components`;const response=await fetch(url,{method:editingComponent?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)}),result=await response.json();if(!response.ok){document.getElementById("connectedComponentError").textContent=result.error;return;}document.getElementById("connectedComponentDialog").close();await refresh();};document.getElementById("cancelRemove").onclick=()=>document.getElementById("removeDialog").close();document.getElementById("confirmRemove").onclick=async()=>{const response=await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(removingComponent.connected_component_id)}`,{method:"DELETE"}),result=await response.json();if(!response.ok){document.getElementById("removeError").textContent=result.error;return;}document.getElementById("removeDialog").close();await refresh();};document.addEventListener("click",event=>{if(!event.target.closest(".row-menu-wrap"))closeComponentMenus();});document.addEventListener("keydown",event=>{if(event.key==="Escape")closeComponentMenus();});refresh().catch(()=>document.getElementById("nodeError").hidden=false);

function renderAllocation(){
    if(!allocation)return;
    const state=document.createElement("span");
    state.className=mappingStateClass(allocation.mapping_state);
    state.textContent=allocation.mapping_state;
    allocationSummary.replaceChildren("Mapping: ",state,` · ${allocation.used} used (${allocation.shared} shared) · ${allocation.free} free`);
    allocationRows.replaceChildren();
    allocation.resources.filter(resource=>allocationFilter==='all'||resource.state!=='Free').forEach(resource=>{
        const tr=document.createElement('tr'),allocations=resource.allocations;
        [resource.resource,resource.state,allocations.map(item=>item.role).join(' · ')||'—',allocations.map(item=>item.interface_signal).join(' · ')||'—'].forEach(value=>{
            const td=document.createElement('td');
            td.textContent=value;
            tr.append(td);
        });
        const td=document.createElement('td');
        allocations.forEach((item,index)=>{
            if(index)td.append(document.createTextNode(' · '));
            const link=document.createElement('a');
            link.href=`/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(item.connected_component_id)}`;
            link.className='usage-count-link';
            link.textContent=item.connected_component;
            td.append(link);
        });
        if(!allocations.length)td.textContent='—';
        tr.append(td);
        allocationRows.append(tr);
    });
}
allocationAll.onclick=()=>{allocationFilter='all';allocationAll.classList.add('active');allocationUsed.classList.remove('active');renderAllocation();};allocationUsed.onclick=()=>{allocationFilter='used';allocationUsed.classList.add('active');allocationAll.classList.remove('active');renderAllocation();};
