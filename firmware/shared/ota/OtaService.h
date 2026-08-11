#pragma once
#include <Arduino.h>
#include <ArduinoOTA.h>

inline void startOta(const char* hostname, const char* password) {
  ArduinoOTA.setHostname(hostname);
  ArduinoOTA.setPassword(password);
  ArduinoOTA.onStart([]() { Serial.println("OTA update starting"); });
  ArduinoOTA.onEnd([]() { Serial.println("OTA update complete"); });
  ArduinoOTA.onError([](ota_error_t error) { Serial.printf("OTA error: %u\n", error); });
  ArduinoOTA.begin();
  Serial.printf("Authenticated OTA ready at %s.local\n", hostname);
}

inline void serviceOta() { ArduinoOTA.handle(); }
