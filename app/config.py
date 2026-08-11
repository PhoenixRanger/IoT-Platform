import os


DB_NAME = "sensor.db"
READING_LIMIT = 20
DEFAULT_NODE_ID = os.getenv("DEFAULT_NODE_ID", "environment_node_001")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensors/+/readings")
