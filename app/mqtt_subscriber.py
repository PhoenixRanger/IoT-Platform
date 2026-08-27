import json
import logging
import math
from numbers import Real

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC
from app.database import (
    CYCLE_ID_PATTERN,
    init_db,
    replace_reported_capabilities,
    save_measurements,
    save_instance_measurement,
    update_device_metadata,
)


RECONNECT_DELAY_SECONDS = 5
METADATA_FIELDS = {
    "node_type",
    "hardware_model",
    "hardware_revision",
    "firmware_name",
    "firmware_version",
    "ota_hostname",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("mqtt_subscriber")


def parse_reading_payload(payload):
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON payload: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object")

    device_id = data.get("node_id", data.get("device_id"))
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Missing node_id")

    metadata = {}
    for field in METADATA_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid metadata value for {field}: {value}")
        metadata[field] = value.strip()

    if "capabilities" in data:
        capabilities = data["capabilities"]
        if not isinstance(capabilities, list) or any(
            not isinstance(key, str) or not key.strip() for key in capabilities
        ):
            raise ValueError("capabilities must be a list of non-empty strings")
        metadata["capabilities"] = list(dict.fromkeys(key.strip() for key in capabilities))

    readings = None
    telemetry_fields = {"instance_id", "cycle_id", "value", "unit"}
    if telemetry_fields & set(data):
        if not telemetry_fields <= set(data):
            raise ValueError("Telemetry requires instance_id, cycle_id, value, and unit")
        if isinstance(data["value"], bool) or not isinstance(data["value"], Real) \
                or not math.isfinite(data["value"]):
            raise ValueError("Telemetry value must be a finite number")
        if not isinstance(data["cycle_id"], str) or not CYCLE_ID_PATTERN.fullmatch(data["cycle_id"]):
            raise ValueError("Malformed cycle ID")
        readings = {field: data[field] for field in telemetry_fields}
        diagnostics = {}
        for field in ("rssi", "uptime_seconds"):
            if field not in data:
                continue
            value = data[field]
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"Invalid diagnostic value for {field}")
            diagnostics[field] = value
        if diagnostics:
            readings["diagnostics"] = diagnostics

    if readings is None and "capabilities" not in metadata:
        raise ValueError("Payload must contain instance-aware telemetry or capabilities metadata")

    return device_id.strip(), metadata, readings


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        if userdata.get("connected_once"):
            logger.info("Successfully reconnected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
        else:
            logger.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
            userdata["connected_once"] = True

        client.subscribe(MQTT_TOPIC)
        logger.info("Subscribed to MQTT topic(s): %s", MQTT_TOPIC)
    else:
        logger.error(
            "MQTT connection failed with reason code %s; retrying every %s seconds",
            reason_code,
            RECONNECT_DELAY_SECONDS,
        )


def on_connect_fail(client, userdata):
    logger.warning(
        "MQTT reconnect attempt failed for %s:%s; retrying in %s seconds",
        MQTT_HOST,
        MQTT_PORT,
        RECONNECT_DELAY_SECONDS,
    )


def on_disconnect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        logger.info("Disconnected from MQTT broker")
    else:
        logger.warning(
            "Disconnected from MQTT broker unexpectedly with reason code %s; reconnecting every %s seconds",
            reason_code,
            RECONNECT_DELAY_SECONDS,
        )


def on_message(client, userdata, message):
    payload = message.payload.decode("utf-8", errors="replace")
    logger.info("Received MQTT topic: %s", message.topic)
    logger.info("Received MQTT payload: %s", payload)

    try:
        device_id, metadata, readings = parse_reading_payload(payload)
    except ValueError as error:
        logger.warning("MQTT payload validation failed: %s", error)
        return

    try:
        capabilities = metadata.pop("capabilities", None)
        update_device_metadata(device_id, metadata)
        if capabilities is not None:
            replace_reported_capabilities(device_id, capabilities)
        if readings:
            diagnostics = readings.pop("diagnostics", {})
            saved = [save_instance_measurement(device_id, **readings)]
            # RSSI and uptime describe the node transport/runtime rather than a
            # sensing or actuation channel, so they remain node diagnostics.
            saved.extend(save_measurements(
                device_id, diagnostics, measurement_cycle_id=readings["cycle_id"]
            ))
        else:
            saved = []
    except ValueError as error:
        logger.warning("MQTT reading validation failed: %s", error)
    except Exception:
        logger.exception("Unexpected exception while saving MQTT message from %s", device_id)
    else:
        logger.info("Successfully inserted %s MQTT reading(s) for %s into SQLite", len(saved), device_id)


def main():
    logger.info("Starting MQTT subscriber")
    logger.info("Initializing SQLite database")
    init_db()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        userdata={"connected_once": False},
    )
    client.on_connect = on_connect
    client.on_connect_fail = on_connect_fail
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(
        min_delay=RECONNECT_DELAY_SECONDS,
        max_delay=RECONNECT_DELAY_SECONDS,
    )

    logger.info(
        "Connecting to MQTT broker at %s:%s and subscribing to %s",
        MQTT_HOST,
        MQTT_PORT,
        MQTT_TOPIC,
    )
    client.connect_async(MQTT_HOST, MQTT_PORT)
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
