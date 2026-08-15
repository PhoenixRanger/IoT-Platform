import json
import logging
import math
from numbers import Real

import paho.mqtt.client as mqtt

from app.config import MQTT_HOST, MQTT_PORT, MQTT_TOPIC
from app.database import init_db, save_measurements, update_device_metadata


RECONNECT_DELAY_SECONDS = 5
SUPPORTED_SENSOR_TYPES = {
    "temperature",
    "humidity",
    "rssi",
    "uptime_seconds",
    "outside_temperature",
    "outside_humidity",
    "outside_pressure",
    "enclosure_temperature",
    "enclosure_humidity",
    "enclosure_pressure",
}
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

    device_id = data.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("Missing device_id")

    metadata = {}
    for field in METADATA_FIELDS:
        if field not in data:
            continue
        value = data[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Invalid metadata value for {field}: {value}")
        metadata[field] = value.strip()

    readings = {}
    for sensor_type in SUPPORTED_SENSOR_TYPES:
        if sensor_type not in data:
            continue

        value = data[sensor_type]
        if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
            raise ValueError(f"Invalid numeric value for {sensor_type}: {value}")
        readings[sensor_type] = value

    if not readings:
        raise ValueError("Payload must contain at least one valid supported reading")

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
        update_device_metadata(device_id, metadata)
        saved = save_measurements(device_id, readings)
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
