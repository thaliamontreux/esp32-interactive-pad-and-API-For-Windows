#ifndef DISPLAYPAD_CONNECTION_MODE_H
#define DISPLAYPAD_CONNECTION_MODE_H

#include <stdint.h>

// Connection mode for host/API communication.
// WIFI      - Use WiFi HTTP/WebSocket only.
// BLUETOOTH - Use BLE JSON bridge only.
// AUTO      - Prefer BLE when available, fall back to WiFi.
enum class ConnectionMode : uint8_t {
    WIFI = 0,
    BLUETOOTH = 1,
    AUTO = 2,
};

ConnectionMode getConnectionMode();
void setConnectionMode(ConnectionMode mode);

#endif
