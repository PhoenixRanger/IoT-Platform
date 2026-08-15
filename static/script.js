let sensorChart = null;
let selectedNodeId = null;
let selectedSensor = null;

const REFRESH_INTERVAL_MS = 5000;

function formatSensorName(sensorType) {
    const labels = {
        outside_temperature: "Outside Temperature",
        outside_humidity: "Outside Humidity",
        outside_pressure: "Outside Air Pressure",
        enclosure_temperature: "Enclosure Temperature",
        enclosure_humidity: "Enclosure Humidity",
        enclosure_pressure: "Enclosure Air Pressure"
    };

    if (labels[sensorType]) {
        return labels[sensorType];
    }

    return sensorType
        .replaceAll("_", " ")
        .replace(/\b\w/g, char => char.toUpperCase());
}

function getSensorUnit(sensorType) {
    const units = {
        temperature: "°C",
        humidity: "%",
        outside_temperature: "°C",
        outside_humidity: "%",
        outside_pressure: "hPa",
        enclosure_temperature: "°C",
        enclosure_humidity: "%",
        enclosure_pressure: "hPa",
        soil_moisture: "%",
        soil_temperature: "°C",
        rssi: "dBm",
        uptime_seconds: "s",
        battery_voltage: "V",
        battery_percentage: "%",
        air_pressure: "hPa",
        light_intensity: "lux",
        rainfall: "mm",
        wind_speed: "m/s",
        wind_direction: "°",
        solar_radiation: "W/m²",
        water_level: "%",
        water_flow: "L/min",
        ph: "pH",
        ec: "mS/cm"
    };

    return units[sensorType] || "";
}

function getSensorTypes(readings) {
    const excludedKeys = ["timestamp", "node_id"];
    const sensorSet = new Set();

    readings.forEach(reading => {
        Object.keys(reading).forEach(key => {
            if (!excludedKeys.includes(key)) {
                sensorSet.add(key);
            }
        });
    });

    return Array.from(sensorSet).sort();
}

async function loadNodes() {
    const response = await fetch("/api/nodes");
    const nodes = await response.json();

    const nodeSelect = document.getElementById("nodeSelect");
    nodeSelect.innerHTML = "";

    nodes.forEach(node => {
        const option = document.createElement("option");
        option.value = node.node_id;
        const nodeName = typeof node.name === "string" ? node.name.trim() : "";
        option.textContent = nodeName || node.node_id;
        nodeSelect.appendChild(option);
    });

    if (nodes.length > 0) {
        selectedNodeId = selectedNodeId || nodes[0].node_id;
        nodeSelect.value = selectedNodeId;
    }
}

async function loadReadings() {
    if (!selectedNodeId) {
        return;
    }

    try {
        const [readingsResponse, statusResponse] = await Promise.all([
            fetch(`/api/readings?node_id=${encodeURIComponent(selectedNodeId)}`),
            fetch(`/api/node-status?node_id=${encodeURIComponent(selectedNodeId)}`)
        ]);
        if (!readingsResponse.ok || !statusResponse.ok) throw new Error("Dashboard request failed");
        renderDashboard(await readingsResponse.json(), await statusResponse.json());
        document.getElementById("dashboardError").hidden = true;
    } catch (error) {
        console.error(error);
        document.getElementById("dashboardError").hidden = false;
    }
}

function renderDashboard(readings, nodeStatus) {
    if (readings.length === 0) {
        renderCards(readings, [], nodeStatus);
        document.getElementById("readingTableHead").innerHTML = "";
        document.getElementById("readingTableBody").innerHTML = "";
        return;
    }

    const sensorTypes = getSensorTypes(readings);

    if (!selectedSensor || !sensorTypes.includes(selectedSensor)) {
        selectedSensor = sensorTypes[0];
    }

    renderSensorSelector(sensorTypes);
    renderCards(readings, sensorTypes, nodeStatus);
    renderChart(readings);
    renderTable(readings, sensorTypes);
}

function renderSensorSelector(sensorTypes) {
    const sensorSelect = document.getElementById("sensorSelect");
    sensorSelect.innerHTML = "";

    sensorTypes.forEach(sensorType => {
        const option = document.createElement("option");
        option.value = sensorType;
        option.textContent = formatSensorName(sensorType);
        sensorSelect.appendChild(option);
    });

    sensorSelect.value = selectedSensor;
}

function renderCards(readings, sensorTypes, nodeStatus) {
    const latest = readings[readings.length - 1];
    const nodeStatusCards = document.getElementById("nodeStatusCards");
    const sensorGroups = {
        outside: document.getElementById("outsideConditionsCards"),
        enclosure: document.getElementById("enclosureConditionsCards"),
        telemetry: document.getElementById("nodeTelemetryCards")
    };

    nodeStatusCards.innerHTML = "";
    Object.values(sensorGroups).forEach(group => {
        group.innerHTML = "";
    });

    const statusCard = document.createElement("a");
    statusCard.className = "card card-status card-link";
    statusCard.href = `/nodes/${encodeURIComponent(selectedNodeId)}`;
    statusCard.setAttribute("aria-label", `View details for ${selectedNodeId}`);
    const status = nodeStatus?.status || "unknown";
    statusCard.innerHTML = `
        <div class="status-badge status-${status}">${formatSensorName(status)}</div>
        <div class="label">Node status</div>
    `;
    nodeStatusCards.appendChild(statusCard);

    const updateCard = document.createElement("div");
    updateCard.className = "card card-status";
    updateCard.innerHTML = `
        <div class="value value-meta">${latest ? latest.timestamp : "--"}</div>
        <div class="label">Last update</div>
    `;
    nodeStatusCards.appendChild(updateCard);

    if (!latest) {
        const emptyCard = document.createElement("div");
        emptyCard.className = "card card-empty";
        emptyCard.innerHTML = `
            <div class="value value-meta">No readings yet</div>
            <div class="label">Sensor telemetry</div>
        `;
        sensorGroups.telemetry.appendChild(emptyCard);
        updateSensorGroupVisibility(sensorGroups);
        return;
    }

    sensorTypes.forEach(sensorType => {
        if (latest[sensorType] === undefined) {
            return;
        }

        const unit = getSensorUnit(sensorType);

        const card = document.createElement("div");
        card.className = "card";

        card.innerHTML = `
            <div class="value">${latest[sensorType].toFixed(1)} ${unit}</div>
            <div class="label">${formatSensorName(sensorType)}</div>
        `;

        let group = sensorGroups.telemetry;
        if (sensorType.startsWith("outside_")) {
            group = sensorGroups.outside;
        } else if (sensorType.startsWith("enclosure_")) {
            group = sensorGroups.enclosure;
        }
        group.appendChild(card);
    });

    updateSensorGroupVisibility(sensorGroups);
}

function updateSensorGroupVisibility(sensorGroups) {
    const sections = {
        outside: document.getElementById("outsideConditionsSection"),
        enclosure: document.getElementById("enclosureConditionsSection"),
        telemetry: document.getElementById("nodeTelemetrySection")
    };

    Object.keys(sensorGroups).forEach(groupName => {
        sections[groupName].hidden = sensorGroups[groupName].children.length === 0;
    });
}

function renderChart(readings) {
    const selectedReadings = readings.filter(reading => reading[selectedSensor] !== undefined);
    const labels = selectedReadings.map(reading => reading.timestamp.split(" ")[1]);
    const values = selectedReadings.map(reading => reading[selectedSensor]);

    const chartTitle = document.getElementById("chartTitle");
    chartTitle.textContent = `${selectedNodeId} — ${formatSensorName(selectedSensor)} over time`;

    const ctx = document.getElementById("sensorChart");
    const unit = getSensorUnit(selectedSensor);

    if (sensorChart === null) {
        sensorChart = new Chart(ctx, {
            type: "line",
            data: {
                labels: labels,
                datasets: [{
                    label: `${formatSensorName(selectedSensor)} ${unit}`,
                    data: values,
                    tension: 0.25
                }]
            },
            options: {
                responsive: true,
                animation: false
            }
        });
    } else {
        sensorChart.data.labels = labels;
        sensorChart.data.datasets[0].label = `${formatSensorName(selectedSensor)} ${unit}`;
        sensorChart.data.datasets[0].data = values;
        sensorChart.update();
    }
}

function renderTable(readings, sensorTypes) {
    const tableHead = document.getElementById("readingTableHead");
    const tableBody = document.getElementById("readingTableBody");

    tableHead.innerHTML = "";
    tableBody.innerHTML = "";

    const headerRow = document.createElement("tr");
    headerRow.innerHTML = `
        <th>Time</th>
        ${sensorTypes.map(sensorType => `<th>${formatSensorName(sensorType)}</th>`).join("")}
    `;
    tableHead.appendChild(headerRow);

    readings.slice().reverse().forEach(reading => {
        const row = document.createElement("tr");

        row.innerHTML = `
            <td>${reading.timestamp}</td>
            ${sensorTypes.map(sensorType => {
                if (reading[sensorType] === undefined) {
                    return "<td>--</td>";
                }

                const unit = getSensorUnit(sensorType);
                return `<td>${reading[sensorType].toFixed(1)} ${unit}</td>`;
            }).join("")}
        `;

        tableBody.appendChild(row);
    });
}

async function initializeDashboard() {
    await loadNodes();
    await loadReadings();

    document.getElementById("nodeSelect").addEventListener("change", async function(event) {
        selectedNodeId = event.target.value;
        selectedSensor = null;
        await loadReadings();
    });

    document.getElementById("sensorSelect").addEventListener("change", async function(event) {
        selectedSensor = event.target.value;
        await loadReadings();
    });

    setInterval(loadReadings, REFRESH_INTERVAL_MS);
}

initializeDashboard();
