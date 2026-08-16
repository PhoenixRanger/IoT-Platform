#include <Arduino.h>
#include <DHT.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include "secrets.h"
#include "diagnostics/NodeIdentity.h"
#include "mqtt/MetadataPayload.h"
#include "ota/OtaService.h"
#include "wifi/WifiConnection.h"

#define DHT_PIN 4
#define DHT_TYPE DHT22

const char* FIRMWARE_NAME = "environment-node";
const char* HARDWARE_MODEL = "az-delivery-esp32-devkitc-v2";
const char* HARDWARE_REVISION = "prototype-a";
const NodeIdentity IDENTITY = {NODE_ID, FIRMWARE_NAME, FIRMWARE_VERSION,
                               HARDWARE_MODEL, HARDWARE_REVISION, OTA_HOSTNAME};
const unsigned long PUBLISH_INTERVAL_MS = 10000;
const char* const CAPABILITIES[] = {
    "temperature_measurement", "humidity_measurement", "wifi"};
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
DHT dht(DHT_PIN, DHT_TYPE);
unsigned long lastPublish = 0;

bool connectMqtt() {
  if (mqttClient.connected()) return true;
  if (!mqttClient.connect(IDENTITY.nodeId)) return false;
  String topic = "sensors/" + String(IDENTITY.nodeId) + "/readings";
  String metadata = capabilityMetadataJson(
      IDENTITY, CAPABILITIES, sizeof(CAPABILITIES) / sizeof(CAPABILITIES[0]));
  mqttClient.publish(topic.c_str(), metadata.c_str());
  return true;
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  mqttClient.setServer(MQTT_SERVER, 1883);
  mqttClient.setBufferSize(512);
  if (connectToWifi(WIFI_SSID, WIFI_PASSWORD)) startOta(IDENTITY.otaHostname, OTA_PASSWORD);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    if (connectToWifi(WIFI_SSID, WIFI_PASSWORD)) startOta(IDENTITY.otaHostname, OTA_PASSWORD);
    return;
  }
  serviceOta();
  if (!connectMqtt()) { delay(250); return; }
  mqttClient.loop();
  if (millis() - lastPublish < PUBLISH_INTERVAL_MS) { delay(10); return; }
  lastPublish = millis();
  float temperature = dht.readTemperature();
  float humidity = dht.readHumidity();
  if (isnan(temperature) || isnan(humidity)) return;
  String json = metadataJson(IDENTITY);
  json += ",\"temperature\":" + String(temperature, 1);
  json += ",\"humidity\":" + String(humidity, 1);
  json += ",\"rssi\":" + String(WiFi.RSSI());
  json += ",\"uptime_seconds\":" + String(millis() / 1000) + "}";
  String topic = "sensors/" + String(IDENTITY.nodeId) + "/readings";
  mqttClient.publish(topic.c_str(), json.c_str());
}
