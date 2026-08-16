import json

import pytest

from app.mqtt_subscriber import parse_reading_payload


def parse(payload):
    return parse_reading_payload(json.dumps(payload))


def test_existing_temperature_humidity_payload_remains_valid():
    device_id, metadata, readings = parse({
        "device_id": "environment_node_001",
        "temperature": 24.8,
        "humidity": 58.0,
        "rssi": -62,
        "uptime_seconds": 1234,
    })

    assert device_id == "environment_node_001"
    assert metadata == {}
    assert readings == {
        "temperature": 24.8,
        "humidity": 58.0,
        "rssi": -62,
        "uptime_seconds": 1234,
    }


def test_full_dual_climate_payload_is_valid():
    payload = {
        "device_id": "irrigation_controller_001",
        "outside_temperature": 24.8,
        "outside_humidity": 61.2,
        "outside_pressure": 1009.4,
        "enclosure_temperature": 31.5,
        "enclosure_humidity": 42.1,
        "rssi": -61,
        "uptime_seconds": 418,
    }

    device_id, metadata, readings = parse(payload)

    assert device_id == payload.pop("device_id")
    assert metadata == {}
    assert readings == payload


@pytest.mark.parametrize("readings", [
    {
        "outside_temperature": 24.8,
        "outside_humidity": 61.2,
        "outside_pressure": 1009.4,
    },
    {
        "enclosure_temperature": 31.5,
        "enclosure_humidity": 42.1,
    },
])
def test_partial_climate_payloads_are_valid(readings):
    _, metadata, parsed_readings = parse({"device_id": "irrigation_controller_001", **readings})
    assert metadata == {}
    assert parsed_readings == readings


def test_payload_containing_only_device_id_is_rejected():
    with pytest.raises(ValueError, match="at least one"):
        parse({"device_id": "irrigation_controller_001"})


@pytest.mark.parametrize("device_id", [None, "", "   "])
def test_missing_or_empty_device_id_is_rejected(device_id):
    payload = {"outside_temperature": 24.8}
    if device_id is not None:
        payload["device_id"] = device_id

    with pytest.raises(ValueError, match="Missing device_id"):
        parse(payload)


def test_unknown_field_is_not_accepted_as_a_measurement():
    _, metadata, readings = parse({
        "device_id": "irrigation_controller_001",
        "outside_temperature": 24.8,
        "soil_probe": 99,
    })
    assert metadata == {}
    assert readings == {"outside_temperature": 24.8}

    with pytest.raises(ValueError, match="at least one"):
        parse({"device_id": "irrigation_controller_001", "soil_probe": 99})


@pytest.mark.parametrize("value", ["warm", "24.8", None, True])
def test_non_numeric_sensor_values_are_rejected(value):
    with pytest.raises(ValueError, match="Invalid numeric value"):
        parse({"device_id": "irrigation_controller_001", "outside_temperature": value})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_sensor_values_are_rejected(value):
    with pytest.raises(ValueError, match="Invalid numeric value"):
        parse({"device_id": "irrigation_controller_001", "outside_temperature": value})


def test_metadata_is_extracted_separately_from_measurements():
    device_id, metadata, readings = parse({
        "device_id": "irrigation_controller_001",
        "firmware_name": "irrigation-controller",
        "firmware_version": "1.0.0",
        "hardware_model": "heltec-wifi-lora-32-v3",
        "hardware_revision": "prototype-a",
        "ota_hostname": "irrigation-controller-001",
        "outside_temperature": 24.8,
    })
    assert device_id == "irrigation_controller_001"
    assert metadata == {
        "firmware_name": "irrigation-controller",
        "firmware_version": "1.0.0",
        "hardware_model": "heltec-wifi-lora-32-v3",
        "hardware_revision": "prototype-a",
        "ota_hostname": "irrigation-controller-001",
    }
    assert readings == {"outside_temperature": 24.8}


def test_invalid_metadata_is_rejected():
    with pytest.raises(ValueError, match="Invalid metadata"):
        parse({"device_id": "node", "firmware_version": 1.0, "rssi": -60})


def test_on_message_persists_metadata_and_measurements(isolated_database):
    from types import SimpleNamespace
    from app.database import get_node, get_recent_measurements
    from app.mqtt_subscriber import on_message

    payload = json.dumps({
        "device_id": "node_001",
        "firmware_name": "environment-node",
        "firmware_version": "1.0.0",
        "hardware_model": "az-delivery-esp32-devkitc-v2",
        "hardware_revision": "prototype-a",
        "temperature": 22.5,
    }).encode()
    on_message(None, None, SimpleNamespace(payload=payload, topic="sensors/node_001/readings"))
    assert get_node("node_001")["firmware_version"] == "1.0.0"
    assert get_recent_measurements("node_001")[0]["temperature"] == 22.5


def test_mqtt_cannot_overwrite_registry_metadata(isolated_database):
    from types import SimpleNamespace
    from app.database import (
        get_node, get_recent_measurements, save_measurements, update_node_registry,
    )
    from app.mqtt_subscriber import on_message

    save_measurements("node_001", {"temperature": 20})
    update_node_registry("node_001", {
        "name": "Server Name", "location": "Server Location", "category": "Climate",
        "latitude": 51.5, "longitude": -0.1, "enabled": False,
    })
    payload = json.dumps({
        "device_id": "node_001", "name": "Device Name", "location": "Device Location",
        "category": "Device Category", "latitude": 0, "longitude": 0, "enabled": True,
        "node_type": "legacy-compatible", "hardware_model": "esp32", "firmware_version": "1.1.0",
        "ota_hostname": "node-001", "temperature": 21,
    }).encode()
    on_message(None, None, SimpleNamespace(payload=payload, topic="sensors/node_001/readings"))

    node = get_node("node_001")
    assert node["name"] == "Server Name"
    assert node["location"] == "Server Location"
    assert node["category"] == "Climate"
    assert node["latitude"] == 51.5
    assert node["longitude"] == -0.1
    assert node["enabled"] is False
    assert node["node_type"] == "legacy-compatible"
    assert node["hardware_model"] == "esp32"
    assert node["firmware_version"] == "1.1.0"
    assert node["ota_hostname"] == "node-001"
    assert get_recent_measurements("node_001")[-1]["temperature"] == 21


def test_capability_only_metadata_payload_is_parsed():
    device_id, metadata, readings = parse({
        "device_id": "node", "capabilities": ["wifi", "wifi", "temperature_measurement"]
    })
    assert device_id == "node"
    assert metadata["capabilities"] == ["wifi", "temperature_measurement"]
    assert readings == {}


@pytest.mark.parametrize("capabilities", ["wifi", [1], [""], None])
def test_malformed_capabilities_are_rejected(capabilities):
    with pytest.raises(ValueError, match="capabilities"):
        parse({"device_id": "node", "capabilities": capabilities, "rssi": -60})


def test_mqtt_reported_capabilities_replace_without_changing_expected(isolated_database):
    from types import SimpleNamespace
    from app.database import get_node_capabilities, replace_expected_capabilities, save_measurements
    from app.mqtt_subscriber import on_message
    save_measurements("node", {"temperature": 20})
    replace_expected_capabilities("node", ["temperature_measurement"])
    for capabilities in [["temperature_measurement", "wifi"], ["humidity_measurement"]]:
        message = SimpleNamespace(payload=json.dumps({
            "device_id": "node", "capabilities": capabilities
        }).encode(), topic="sensors/node/readings")
        on_message(None, None, message)
    comparison = get_node_capabilities("node")
    assert [item["capability_key"] for item in comparison["expected"]] == ["temperature_measurement"]
    assert [item["capability_key"] for item in comparison["reported"]] == ["humidity_measurement"]
    assert comparison["reported_at"] is not None


def test_unknown_mqtt_capability_keeps_previous_set_and_registry(isolated_database):
    from types import SimpleNamespace
    from app.database import get_capabilities, get_node_capabilities, replace_reported_capabilities
    from app.mqtt_subscriber import on_message
    replace_reported_capabilities("node", ["wifi"])
    before = {item["capability_key"] for item in get_capabilities()}
    on_message(None, None, SimpleNamespace(payload=json.dumps({
        "device_id": "node", "capabilities": ["unregistered_capability"]
    }).encode(), topic="sensors/node/readings"))
    assert {item["capability_key"] for item in get_capabilities()} == before
    assert [item["capability_key"] for item in get_node_capabilities("node")["reported"]] == ["wifi"]
