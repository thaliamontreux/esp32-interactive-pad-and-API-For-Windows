#include "discovery_beacon.h"
#include "config.h"
#include "storage.h"

DiscoveryBeacon discovery;

DiscoveryBeacon::DiscoveryBeacon()
    : lastBeaconTime(0), assigned(false), initialized(false) {}

bool DiscoveryBeacon::begin() {
    // Don't initialize UDP until WiFi is connected
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[Discovery] Waiting for WiFi before starting UDP...");
        return false;
    }
    return initUDP();
}

bool DiscoveryBeacon::initUDP() {
    if (initialized) return true;
    if (WiFi.status() != WL_CONNECTED) return false;

    // Start UDP for broadcasting beacons
    if (!udpBeacon.begin(DISCOVERY_BROADCAST_PORT)) {
        Serial.println("[Discovery] Failed to start beacon UDP");
        return false;
    }

    // Start UDP for listening to assignments
    if (!udpListener.begin(DISCOVERY_LISTEN_PORT)) {
        Serial.println("[Discovery] Failed to start listener UDP");
        udpBeacon.stop();
        return false;
    }

    initialized = true;
    Serial.println("[Discovery] Beacon system ready");
    Serial.printf("[Discovery] Broadcasting on port %d, listening on port %d\n",
                  DISCOVERY_BROADCAST_PORT, DISCOVERY_LISTEN_PORT);
    Serial.printf("[Discovery] My IP: %s\n", WiFi.localIP().toString().c_str());
    return true;
}

void DiscoveryBeacon::loop() {
    // Try to initialize if not ready yet
    if (!initialized) {
        if (millis() % 1000 < 100) {  // Try every ~1 second
            initUDP();
        }
        return;
    }

    // Check for assignment packets
    checkForAssignment();

    // Send beacon periodically
    unsigned long now = millis();
    if (now - lastBeaconTime >= BEACON_INTERVAL_MS) {
        sendBeacon();
        lastBeaconTime = now;
    }
}

void DiscoveryBeacon::sendBeacon() {
    if (!initialized || WiFi.status() != WL_CONNECTED) return;

    BeaconPacket packet;
    memcpy(packet.magic, BEACON_MAGIC, 6);
    packet.version = 1;
    packet.type = DiscoveryPacketType::BEACON;

    // Copy pad UUID
    String uuid = storage.getPadUUID();
    strncpy(packet.pad_uuid, uuid.c_str(), 31);
    packet.pad_uuid[31] = '\0';

    // Copy MAC address
    String mac = WiFi.macAddress();
    strncpy(packet.mac, mac.c_str(), 17);
    packet.mac[17] = '\0';

    // Display info
    packet.screen_width = SCREEN_WIDTH;
    packet.screen_height = SCREEN_HEIGHT;
    packet.button_count = 6;  // Default

    // Network info
    packet.port = 80;
    packet.flags = assigned ? 0x01 : 0x00;  // Flag if already assigned

    // Broadcast to subnet
    IPAddress broadcastIP = ~WiFi.subnetMask() | WiFi.gatewayIP();

    udpBeacon.beginPacket(broadcastIP, DISCOVERY_BROADCAST_PORT);
    udpBeacon.write((uint8_t*)&packet, sizeof(packet));
    udpBeacon.endPacket();

    static int beaconCount = 0;
    if (++beaconCount % 12 == 0) {  // Log every minute
        Serial.printf("[Discovery] Beacon #%d sent to %s\n", beaconCount, broadcastIP.toString().c_str());
    }
}

void DiscoveryBeacon::checkForAssignment() {
    if (!initialized) return;
    int packetSize = udpListener.parsePacket();
    if (packetSize < (int)sizeof(AssignPacket)) return;

    AssignPacket packet;
    int len = udpListener.read((uint8_t*)&packet, sizeof(packet));
    if (len < sizeof(packet)) return;

    // Verify magic
    if (memcmp(packet.magic, BEACON_MAGIC, 6) != 0) return;
    if (packet.version != 1) return;
    if (packet.type != DiscoveryPacketType::ASSIGN) return;

    // Check if this is for us
    String myUUID = storage.getPadUUID();
    if (strncmp(packet.pad_uuid, myUUID.c_str(), myUUID.length()) != 0) {
        return;  // Not for us
    }

    Serial.println("[Discovery] Received ASSIGN packet from server!");
    Serial.printf("[Discovery] Device token: %.8s...\n", packet.device_token);
    Serial.printf("[Discovery] API UUID: %s\n", packet.api_uuid);

    // Store the assignment
    assignedToken = String(packet.device_token);
    assignedApiUUID = String(packet.api_uuid);
    assigned = true;

    // Save to storage
    storage.setDeviceToken(assignedToken);
    storage.setApiUUID(assignedApiUUID);
    storage.setPaired(true);

    // Get server IP from packet
    IPAddress serverIP = udpListener.remoteIP();
    storage.setApiHost(serverIP.toString());
    storage.setApiIP(serverIP.toString());
    storage.setApiPort(packet.api_port);

    Serial.println("[Discovery] Assignment saved! Sending ACK...");

    // Send acknowledgment
    sendAck();

    // Notify that we're ready to download config
    Serial.println("[Discovery] Ready to download configuration!");
}

void DiscoveryBeacon::sendAck() {
    struct __attribute__((packed)) AckPacket {
        char magic[6];
        uint8_t version;
        DiscoveryPacketType type;
        char pad_uuid[32];
        uint8_t status;
    };

    AckPacket packet;
    memcpy(packet.magic, BEACON_MAGIC, 6);
    packet.version = 1;
    packet.type = DiscoveryPacketType::ACK;

    String uuid = storage.getPadUUID();
    strncpy(packet.pad_uuid, uuid.c_str(), 31);
    packet.pad_uuid[31] = '\0';
    packet.status = 0;  // OK

    udpBeacon.beginPacket(udpListener.remoteIP(), DISCOVERY_BROADCAST_PORT);
    udpBeacon.write((uint8_t*)&packet, sizeof(packet));
    udpBeacon.endPacket();
}
