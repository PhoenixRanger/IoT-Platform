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
