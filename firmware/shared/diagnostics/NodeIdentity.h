#pragma once

struct NodeIdentity {
  const char* nodeId;
  const char* firmwareName;
  const char* firmwareVersion;
  const char* hardwareModel;
  const char* hardwareRevision;
  const char* otaHostname;
};
