const capabilities = [
    ['digital_input', 'Digital In'], ['digital_output', 'Digital Out'], ['pwm', 'PWM'],
    ['adc', 'ADC'], ['dac', 'DAC'], ['i2c_sda', 'I²C SDA'], ['i2c_scl', 'I²C SCL'],
    ['spi_mosi', 'SPI MOSI'], ['spi_miso', 'SPI MISO'], ['spi_sck', 'SPI SCK'],
    ['spi_cs', 'SPI CS'], ['uart_tx', 'UART TX'], ['uart_rx', 'UART RX'],
];
let platforms = [], editing = null;

function checkbox(value, checked = false) {
    const input = document.createElement('input');
    input.type = 'checkbox';
    if (value) input.dataset.capability = value;
    input.checked = checked;
    return input;
}

function syncSelectAll(tr) {
    const individual = Array.from(tr.querySelectorAll('[data-capability]'));
    const selectAll = tr.querySelector('.select-all-capabilities');
    const checkedCount = individual.filter(input => input.checked).length;
    selectAll.checked = checkedCount === individual.length;
    selectAll.indeterminate = checkedCount > 0 && checkedCount < individual.length;
}

function resourceRow(item = {resource: '', capabilities: []}) {
    const tr = document.createElement('tr'), nameCell = document.createElement('td');
    const name = document.createElement('input');
    name.className = 'resource-name';
    name.placeholder = 'GPIO21 / PA9 / D13';
    name.required = true;
    name.value = item.resource;
    nameCell.append(name);
    tr.append(nameCell);
    capabilities.forEach(([key]) => {
        const td = document.createElement('td'), input = checkbox(key, item.capabilities.includes(key));
        input.onchange = () => syncSelectAll(tr);
        td.append(input);
        tr.append(td);
    });
    const selectAllCell = document.createElement('td'), selectAll = checkbox();
    selectAll.className = 'select-all-capabilities';
    selectAll.setAttribute('aria-label', `Select all capabilities for ${item.resource || 'this pin'}`);
    selectAll.onchange = () => {
        tr.querySelectorAll('[data-capability]').forEach(input => { input.checked = selectAll.checked; });
        syncSelectAll(tr);
    };
    selectAllCell.append(selectAll);
    tr.append(selectAllCell);
    const removeCell = document.createElement('td'), remove = document.createElement('button');
    remove.type = 'button';
    remove.textContent = 'Remove';
    remove.onclick = () => tr.remove();
    removeCell.append(remove);
    tr.append(removeCell);
    document.getElementById('resourceRows').append(tr);
    syncSelectAll(tr);
}

function closePlatformMenus(except = null) {
    document.querySelectorAll('.platform-action-menu').forEach(menu => {
        if (menu === except || menu.hidden) return;
        menu.hidden = true;
        menu.previousElementSibling?.setAttribute('aria-expanded', 'false');
        menu.closest('tr')?.classList.remove('menu-open');
    });
}

function render() {
    const body = document.getElementById('platformRows');
    body.replaceChildren();
    platforms.forEach(item => {
        const tr = document.createElement('tr');
        [item.display_name, `${item.manufacturer} / ${item.model}`, item.mcu,
         item.revision || '—', String(item.resources.length)].forEach(value => {
            const td = document.createElement('td');
            td.textContent = value;
            tr.append(td);
        });
        const usage = document.createElement('td'), usageLink = document.createElement('a');
        usageLink.className = 'usage-count-link';
        usageLink.href = `/nodes?hardware_platform=${encodeURIComponent(item.hardware_platform_id)}`;
        usageLink.textContent = String(item.active_node_count);
        usage.append(usageLink);
        tr.append(usage);

        const actions = document.createElement('td'), wrap = document.createElement('div');
        const trigger = document.createElement('button'), menu = document.createElement('div');
        actions.className = 'fleet-menu-column';
        wrap.className = 'menu-wrap row-menu-wrap';
        trigger.type = 'button';
        trigger.className = 'kebab-button';
        trigger.textContent = '⋮';
        trigger.setAttribute('aria-label', `Actions for ${item.display_name}`);
        trigger.setAttribute('aria-expanded', 'false');
        menu.className = 'action-menu row-action-menu platform-action-menu';
        menu.hidden = true;
        const menuActions = item.technical_locked
            ? [['View / Edit Details', () => openForm(item)]]
            : [['Edit', () => openForm(item)], ['Delete', () => deletePlatform(item)]];
        menuActions.forEach(([text, action]) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = text;
            button.onclick = () => { closePlatformMenus(); action(); };
            menu.append(button);
        });
        trigger.onclick = () => {
            const opening = menu.hidden;
            closePlatformMenus(menu);
            menu.hidden = !opening;
            trigger.setAttribute('aria-expanded', String(opening));
            tr.classList.toggle('menu-open', opening);
        };
        wrap.append(trigger, menu);
        actions.append(wrap);
        tr.append(actions);
        body.append(tr);
    });
    if (!platforms.length) body.innerHTML = '<tr><td colspan="7" class="fleet-empty">No Hardware Platform definitions.</td></tr>';
}

function openForm(item = null) {
    closePlatformMenus();
    editing = item;
    document.getElementById('platformDialogTitle').textContent = item ? 'Hardware Platform Details' : 'Create Hardware Platform';
    for (const [id, key] of [['displayName', 'display_name'], ['manufacturer', 'manufacturer'], ['model', 'model'], ['mcu', 'mcu'], ['revision', 'revision'], ['description', 'description']]) document.getElementById(id).value = item?.[key] || '';
    const locked = !!item?.technical_locked;
    document.getElementById('lockNotice').hidden = !locked;
    ['manufacturer', 'model', 'mcu', 'revision'].forEach(id => { document.getElementById(id).disabled = locked; });
    document.getElementById('resourceEditor').disabled = locked;
    document.getElementById('resourceRows').replaceChildren();
    (item?.resources || []).forEach(resourceRow);
    document.getElementById('formError').textContent = '';
    document.getElementById('platformDialog').showModal();
}

async function deletePlatform(item) {
    closePlatformMenus();
    if (!confirm(`Delete “${item.display_name}”?`)) return;
    const response = await fetch(`/api/hardware-platforms/${item.hardware_platform_id}`, {method: 'DELETE'});
    if (response.ok) load();
}

document.getElementById('resourceHead').append(
    ...capabilities.map(([, label]) => { const th = document.createElement('th'); th.textContent = label; return th; }),
    ...['Select all', ''].map(label => { const th = document.createElement('th'); th.textContent = label; return th; })
);
document.getElementById('addResource').onclick = () => resourceRow();
document.getElementById('createPlatform').onclick = () => openForm();
document.getElementById('cancelPlatform').onclick = () => document.getElementById('platformDialog').close();
document.getElementById('platformForm').onsubmit = async event => {
    event.preventDefault();
    const payload = {display_name: document.getElementById('displayName').value, description: document.getElementById('description').value || null};
    if (!editing?.technical_locked) Object.assign(payload, {
        manufacturer: document.getElementById('manufacturer').value,
        model: document.getElementById('model').value,
        mcu: document.getElementById('mcu').value,
        revision: document.getElementById('revision').value || null,
        resources: Array.from(document.querySelectorAll('#resourceRows tr'), tr => ({
            resource: tr.querySelector('.resource-name').value,
            capabilities: Array.from(tr.querySelectorAll('[data-capability]:checked'), input => input.dataset.capability),
        })),
    });
    const url = editing ? `/api/hardware-platforms/${editing.hardware_platform_id}` : '/api/hardware-platforms';
    const response = await fetch(url, {method: editing ? 'PATCH' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)}), result = await response.json();
    if (!response.ok) { document.getElementById('formError').textContent = result.error; return; }
    document.getElementById('platformDialog').close();
    load();
};
document.addEventListener('click', event => { if (!event.target.closest('.row-menu-wrap')) closePlatformMenus(); });
document.addEventListener('keydown', event => { if (event.key === 'Escape') closePlatformMenus(); });
async function load() { const response = await fetch('/api/hardware-platforms'); platforms = await response.json(); render(); }
load();
