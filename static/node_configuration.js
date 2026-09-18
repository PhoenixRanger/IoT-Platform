const root=document.getElementById("configurationRoot"),nodeId=root.dataset.nodeId;let node=null,definitions=[],connectedComponents=[],editingComponent=null,removingComponent=null,allocation=null,runtimeConfiguration=null,allocationFilter="all";
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
function render(){document.getElementById("nodeHeading").textContent=`${node.name} — Configuration`;document.getElementById("nodeTechnicalId").textContent=node.node_id;renderComponents();renderAllocation();renderRuntime();}
function showPreview(){const item=definitions.find(x=>x.definition_key===document.getElementById("componentDefinition").value),preview=document.getElementById("definitionPreview");preview.textContent=item?`${item.display_name} · ${item.interfaces.map(x=>x.replaceAll("_"," ")).join(", ")||"No interface"} · ${item.capabilities.map(x=>x.display_name).join(", ")||"No capabilities"}`:"";}
function openComponent(item=null){editingComponent=item;const select=document.getElementById("componentDefinition");select.replaceChildren();definitions.forEach(def=>{const option=document.createElement("option");option.value=def.definition_key;option.textContent=def.display_name;select.append(option);});document.getElementById("connectedComponentDialogTitle").textContent=item?"Edit Component":"Add Component";select.disabled=!!item;select.value=item?.definition_key||definitions[0]?.definition_key||"";document.getElementById("connectedComponentLabel").value=item?.label||"";document.getElementById("connectedComponentLocation").value=item?.location??node.location??"";document.getElementById("connectedComponentZone").value=item?.zone||"";document.getElementById("connectedComponentError").textContent="";showPreview();document.getElementById("connectedComponentDialog").showModal();}
function openRemove(item){removingComponent=item;document.getElementById("removeError").textContent="";document.getElementById("removeDialog").showModal();}
async function refresh(){const responses=await Promise.all([fetch(`/api/nodes/${encodeURIComponent(nodeId)}`),fetch("/api/components"),fetch(`/api/nodes/${encodeURIComponent(nodeId)}/components`),fetch(`/api/nodes/${encodeURIComponent(nodeId)}/hardware-allocation`),fetch(`/api/nodes/${encodeURIComponent(nodeId)}/runtime-configuration`)]);if(responses.some(x=>!x.ok))throw new Error();[node,definitions,connectedComponents,allocation,runtimeConfiguration]=await Promise.all(responses.map(x=>x.json()));render();}
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

function renderRuntime(){
    if(!runtimeConfiguration)return;
    runtimeRevision.textContent=runtimeConfiguration.runtime_configuration_revision;
    runtimeComponents.replaceChildren();
    runtimeConfiguration.components.forEach(component=>{
        const card=document.createElement("section");card.className="card runtime-card";
        card.dataset.componentId=component.connected_component_id;
        const heading=document.createElement("div");heading.className="runtime-card-heading";
        const identity=document.createElement("div"),title=document.createElement("h2"),model=document.createElement("p");
        title.textContent=component.label;model.className="muted";model.textContent=component.component_definition.display_name;
        identity.append(title,model);
        const physical=connectedComponents.find(item=>item.connected_component_id===component.connected_component_id);
        const mapping=document.createElement("span");mapping.className=`mapping-badge ${mappingStateClass(physical?.mapping_state||"Unmapped")}`;mapping.textContent=physical?.mapping_state||"Unmapped";
        heading.append(identity,mapping);card.append(heading);
        const form=document.createElement("form");form.className="runtime-form";
        const toggle=document.createElement("input");toggle.type="checkbox";toggle.checked=component.enabled;toggle.className="runtime-toggle";toggle.setAttribute("aria-label",`Enabled for ${component.label}`);
        const toggleLabel=document.createElement("label");toggleLabel.className="configured-state";const stateText=document.createElement("span");stateText.innerHTML="<strong>Configured State</strong><small>Enabled</small>";toggleLabel.append(stateText,toggle);form.append(toggleLabel);
        const inputs={};const settings=Object.values(component.settings);
        if(!settings.length){const empty=document.createElement("p");empty.className="runtime-empty muted";empty.textContent="No runtime settings";form.append(empty);}
        else {const settingsHeading=document.createElement("h3");settingsHeading.textContent="Runtime Settings";form.append(settingsHeading);}
        settings.forEach(setting=>{const wrap=document.createElement("div");wrap.className="runtime-setting";const label=document.createElement("label");const inputId=`runtime-${component.connected_component_id}-${setting.setting_key}`;label.htmlFor=inputId;label.textContent=setting.display_name;const control=document.createElement("div");control.className="runtime-setting-control";const input=document.createElement("input");input.id=inputId;input.type="number";input.required=true;input.min=setting.minimum;input.max=setting.maximum;input.step="1";input.value=setting.effective_value;inputs[setting.setting_key]=input;const unit=document.createElement("span");unit.textContent=setting.unit||"";control.append(input,unit);const help=document.createElement("small");help.textContent=`Default: ${setting.default_value} · Range: ${setting.minimum}–${setting.maximum}`;wrap.append(label,control,help);form.append(wrap);});
        form.addEventListener("input",updateRuntimeDirtyState);form.addEventListener("change",updateRuntimeDirtyState);
        card.append(form);runtimeComponents.append(card);
    });
    runtimeMessage.textContent="";runtimeMessage.className="";updateRuntimeDirtyState();
}
function runtimeCandidate(component){const card=runtimeComponents.querySelector(`[data-component-id="${CSS.escape(component.connected_component_id)}"]`),settings={};Object.keys(component.settings).forEach(key=>{settings[key]=Number(card.querySelector(`#${CSS.escape(`runtime-${component.connected_component_id}-${key}`)}`).value);});return {enabled:card.querySelector('.runtime-toggle').checked,settings};}
function dirtyRuntimeComponents(){return runtimeConfiguration.components.filter(component=>{const candidate=runtimeCandidate(component);return candidate.enabled!==component.enabled||Object.entries(candidate.settings).some(([key,value])=>value!==component.settings[key].effective_value);});}
function updateRuntimeDirtyState(){const dirty=dirtyRuntimeComponents(),valid=Array.from(runtimeComponents.querySelectorAll("form")).every(form=>form.checkValidity());runtimeSave.disabled=!dirty.length||!valid;runtimeDiscard.disabled=!dirty.length;}
runtimeDiscard.onclick=()=>renderRuntime();
runtimeSave.onclick=async()=>{const dirty=dirtyRuntimeComponents();runtimeSave.disabled=true;runtimeDiscard.disabled=true;runtimeMessage.className="muted";runtimeMessage.textContent="Saving…";let saved=0;for(const component of dirty){const response=await fetch(`/api/nodes/${encodeURIComponent(nodeId)}/components/${encodeURIComponent(component.connected_component_id)}/runtime-configuration`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(runtimeCandidate(component))}),result=await response.json();if(!response.ok){await refresh();runtimeMessage.className="error-message";runtimeMessage.textContent=`Configuration save stopped after ${saved} component${saved===1?"":"s"}. ${(result.validation_errors||[]).map(item=>item.message).join(" ")||result.error}`;return;}saved+=1;runtimeRevision.textContent=result.runtime_configuration_revision;}await refresh();runtimeMessage.className="success-message";runtimeMessage.textContent="Configuration saved.";};
function showConfigurationPanel(runtime){physicalPanel.hidden=runtime;runtimePanel.hidden=!runtime;physicalTab.classList.toggle("active",!runtime);runtimeTab.classList.toggle("active",runtime);}
physicalTab.onclick=()=>showConfigurationPanel(false);runtimeTab.onclick=()=>showConfigurationPanel(true);
