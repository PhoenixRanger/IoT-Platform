#pragma once
#include <Arduino.h>
#include <WiFi.h>

inline bool connectToWifi(const char* ssid, const char* password) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi");
  for (int attempt = 0; WiFi.status() != WL_CONNECTED && attempt < 30; ++attempt) {
    delay(1000);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("Wi-Fi connection failed (status %d).\n", WiFi.status());
    return false;
  }
  Serial.print("Wi-Fi connected; IP: ");
  Serial.println(WiFi.localIP());
  return true;
}
