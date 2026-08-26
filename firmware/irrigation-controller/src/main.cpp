#include <Arduino.h>
#include <Adafruit_MS8607.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include "secrets.h"
#include "diagnostics/NodeIdentity.h"
#include "mqtt/MetadataPayload.h"
#include "ota/OtaService.h"
#include "wifi/WifiConnection.h"

#define DHT_PIN 47
#define DHT_TYPE DHT22
#define MS8607_SDA_PIN 41
#define MS8607_SCL_PIN 42

const char* FIRMWARE_NAME = "irrigation-controller";
const char* HARDWARE_MODEL = "heltec-wifi-lora-32-v3";
const char* HARDWARE_REVISION = "prototype-a";
const NodeIdentity IDENTITY = {NODE_ID, FIRMWARE_NAME, FIRMWARE_VERSION,
                               HARDWARE_MODEL, HARDWARE_REVISION, OTA_HOSTNAME};
const unsigned long PUBLISH_INTERVAL_MS = 10000;
const char* const CAPABILITIES[] = {
    "temperature_measurement", "humidity_measurement",
    "pressure_measurement", "wifi"};
const unsigned long MS8607_RECOVERY_INTERVAL_MS = 30000;
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHT dht(DHT_PIN, DHT_TYPE);
Adafruit_MS8607 ms8607;
bool ms8607Available = false;
unsigned long lastPublish = 0;
unsigned long lastMs8607RecoveryAttempt = 0;

void publishReading(const char* instanceId, float value, const char* unit, bool includeDiagnostics = false) {
  if (isnan(value) || isinf(value)) return;
  String json = "{\"node_id\":\"" + String(IDENTITY.nodeId) + "\"";
  json += ",\"instance_id\":\"" + String(instanceId) + "\"";
  json += ",\"value\":" + String(value, 1) + ",\"unit\":\"" + String(unit) + "\"}";
  if (includeDiagnostics) {
    json.remove(json.length() - 1);
    json += ",\"rssi\":" + String(WiFi.RSSI());
    json += ",\"uptime_seconds\":" + String(millis() / 1000) + "}";
  }
  String topic = "sensors/" + String(IDENTITY.nodeId) + "/readings";
  mqttClient.publish(topic.c_str(), json.c_str());
}

bool connectMqtt() {
  if (mqttClient.connected()) return true;
  if (!mqttClient.connect(IDENTITY.nodeId)) return false;
  String topic = "sensors/" + String(IDENTITY.nodeId) + "/readings";
  String metadata = capabilityMetadataJson(
      IDENTITY, CAPABILITIES, sizeof(CAPABILITIES) / sizeof(CAPABILITIES[0]));
  mqttClient.publish(topic.c_str(), metadata.c_str());
  return true;
}

void recoverMs8607IfNeeded() {
  if (ms8607Available ||
      millis() - lastMs8607RecoveryAttempt < MS8607_RECOVERY_INTERVAL_MS) {
    return;
  }

  lastMs8607RecoveryAttempt = millis();
  Serial.println("Retrying MS8607 initialization...");
  ms8607Available = ms8607.begin(&Wire);
  if (ms8607Available) {
    Serial.println("MS8607 recovered; outside readings will resume.");
  } else {
    Serial.println("MS8607 recovery failed; DHT22 and node telemetry remain available.");
  }
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  Wire.begin(MS8607_SDA_PIN, MS8607_SCL_PIN);
  ms8607Available = ms8607.begin(&Wire);
  if (ms8607Available) {
    Serial.println("MS8607 initialized.");
  } else {
    Serial.println("MS8607 initialization failed; retrying every 30 seconds.");
    lastMs8607RecoveryAttempt = millis();
  }
  mqttClient.setServer(MQTT_SERVER, 1883);
  mqttClient.setBufferSize(768);
  if (connectToWifi(WIFI_SSID, WIFI_PASSWORD)) startOta(IDENTITY.otaHostname, OTA_PASSWORD);
}

void loop() {
  recoverMs8607IfNeeded();

  if (WiFi.status() != WL_CONNECTED) {
    if (connectToWifi(WIFI_SSID, WIFI_PASSWORD)) startOta(IDENTITY.otaHostname, OTA_PASSWORD);
    return;
  }
  serviceOta();
  if (!connectMqtt()) { delay(250); return; }
  mqttClient.loop();
  if (millis() - lastPublish < PUBLISH_INTERVAL_MS) { delay(10); return; }
  lastPublish = millis();
  publishReading(ENCLOSURE_TEMPERATURE_INSTANCE_ID, dht.readTemperature(), "C", true);
  publishReading(ENCLOSURE_HUMIDITY_INSTANCE_ID, dht.readHumidity(), "%");
  if (ms8607Available) {
    sensors_event_t pressure, temperature, humidity;
    if (ms8607.getEvent(&pressure, &temperature, &humidity)) {
      publishReading(OUTSIDE_TEMPERATURE_INSTANCE_ID, temperature.temperature, "C");
      publishReading(OUTSIDE_HUMIDITY_INSTANCE_ID, humidity.relative_humidity, "%");
      publishReading(OUTSIDE_PRESSURE_INSTANCE_ID, pressure.pressure, "hPa");
    }
  }
}
