#pragma once
#include <Arduino.h>
#include "diagnostics/NodeIdentity.h"

inline String metadataJson(const NodeIdentity& identity) {
  String json = "{\"device_id\":\"" + String(identity.nodeId) + "\"";
  json += ",\"firmware_name\":\"" + String(identity.firmwareName) + "\"";
  json += ",\"firmware_version\":\"" + String(identity.firmwareVersion) + "\"";
  json += ",\"hardware_model\":\"" + String(identity.hardwareModel) + "\"";
  json += ",\"hardware_revision\":\"" + String(identity.hardwareRevision) + "\"";
  json += ",\"ota_hostname\":\"" + String(identity.otaHostname) + "\"";
  return json;
}
