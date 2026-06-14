#ifndef DISCOVERY_BEACON_H
#define DISCOVERY_BEACON_H

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>

// Discovery beacon settings
#define DISCOVERY_BROADCAST_PORT 7444
#define DISCOVERY_LISTEN_PORT 7445
#define BEACON_INTERVAL_MS 5000  // Broadcast every 5 seconds
#define BEACON_MAGIC "DSPPAD"    // Magic header to identify our packets

// Discovery packet types
enum class DiscoveryPacketType : uint8_t {
    BEACON = 1,      // ESP32 broadcasting presence
    ASSIGN = 2,      // Server assigning device token
    ACK = 3          // ESP32 acknowledging assignment
};

// Beacon packet structure (broadcast by ESP32)
struct __attribute__((packed)) BeaconPacket {
    char magic[6];           // "DSPPAD"
    uint8_t version;         // Protocol version
    DiscoveryPacketType type; // BEACON
    char pad_uuid[32];       // Pad UUID
    char mac[18];            // MAC address
    uint16_t screen_width;   // Display width
    uint16_t screen_height;  // Display height
    uint8_t button_count;    // Number of buttons
    uint16_t port;           // API port (usually 80)
    uint8_t flags;           // Status flags
};

// Assignment packet (sent by server)
struct __attribute__((packed)) AssignPacket {
    char magic[6];           // "DSPPAD"
    uint8_t version;         // Protocol version
    DiscoveryPacketType type; // ASSIGN
    char pad_uuid[32];       // Pad UUID to assign
    char device_token[64];   // Device token (base64-ish)
    char api_uuid[32];       // API UUID
    uint16_t api_port;       // API port
};

class DiscoveryBeacon {
public:
    DiscoveryBeacon();
    bool begin();
    void loop();  // Call regularly
    bool isAssigned() { return assigned; }
    String getAssignedToken() { return assignedToken; }
    String getAssignedApiUUID() { return assignedApiUUID; }

private:
    WiFiUDP udpBeacon;
    WiFiUDP udpListener;
    unsigned long lastBeaconTime;
    bool assigned;
    bool initialized;
    String assignedToken;
    String assignedApiUUID;

    bool initUDP();  // Initialize UDP once WiFi is ready
    void sendBeacon();
    void checkForAssignment();
    void sendAck();
};

extern DiscoveryBeacon discovery;

#endif
