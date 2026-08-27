#pragma once

#include <Arduino.h>
#include <esp_system.h>

class CycleIdentity {
 public:
  void begin() {
    bootId_ = (static_cast<uint64_t>(esp_random()) << 32) | esp_random();
    sequence_ = 0;
  }

  String next() {
    ++sequence_;
    char cycleId[41];
    snprintf(cycleId, sizeof(cycleId), "cy_%08lx%08lx_%lu",
             static_cast<unsigned long>(bootId_ >> 32),
             static_cast<unsigned long>(bootId_),
             static_cast<unsigned long>(sequence_));
    return String(cycleId);
  }

 private:
  uint64_t bootId_ = 0;
  uint32_t sequence_ = 0;
};
