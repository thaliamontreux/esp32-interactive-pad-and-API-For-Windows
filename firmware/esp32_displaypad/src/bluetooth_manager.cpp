#include "bluetooth_manager.h"

#include <NimBLEDevice.h>
#include <ArduinoJson.h>
#include <esp_bt.h>
#include <deque>
#include "storage.h"
#include "config.h"

BluetoothManager btManager;

// Custom BLE GATT UUIDs for the DisplayPad JSON transport. These are only
// used on the ESP32 side; the host-side BLE bridge will use the same values
// when discovering and connecting to pads.
static const char* DP_BLE_SERVICE_UUID       = "12345678-1234-1234-1234-1234567890ab";
static const char* DP_BLE_CHAR_TX_UUID       = "12345678-1234-1234-1234-1234567890ac";  // Pad -> host (notify)
static const char* DP_BLE_CHAR_RX_UUID       = "12345678-1234-1234-1234-1234567890ad";  // Host -> pad (write)

// NimBLE objects owned at the translation-unit level so they can be accessed
// from callbacks without needing to expose additional methods on
// BluetoothManager.
static NimBLEServer*        g_bleServer        = nullptr;
static NimBLEService*       g_bleService       = nullptr;
static NimBLECharacteristic* g_bleCharTx       = nullptr;
static NimBLECharacteristic* g_bleCharRx       = nullptr;
static bool                 g_bleConnected     = false;

// Current BLE pairing passkey as an integer. NimBLE's default
// onPassKeyDisplay() returns a hardcoded 123456, so we must return this value
// from our own callback for the displayed PIN to actually be accepted.
static uint32_t             g_currentPasskey   = 0;

// Incoming data buffering shared between the RX characteristic callback and
// the BluetoothManager API. We accumulate bytes into a line buffer and
// produce newline-delimited JSON messages.
static String               g_rxLineBuffer;
static std::vector<String>  g_pendingLines;

// Timestamps (millis) of the most recent BLE RX/TX activity. These are used
// by the UI to drive RX/TX status indicators in the taskbar when operating in
// Bluetooth mode.
static unsigned long        g_lastRxActivityMs = 0;
static unsigned long        g_lastTxActivityMs = 0;
static const size_t         BLE_NOTIFY_CHUNK_SIZE = 20;
static std::deque<String>   g_txQueue;
static String               g_txActiveLine;
static size_t               g_txActiveOffset = 0;
static unsigned long        g_nextTxChunkAtMs = 0;

// Some ESP32 builds or previous uses of the classic Bluetooth stack can leave
// the BT controller in a non-idle state. NimBLEDevice::init() expects the
// controller to be idle, otherwise esp_bt_controller_init() returns
// ESP_ERR_INVALID_STATE and aborts. This helper gently forces the controller
// back to IDLE before we hand control to NimBLE.
static void ensureBtControllerIdle() {
    esp_bt_controller_status_t status = esp_bt_controller_get_status();

    Serial.print("[BLE] BT controller status before init: ");
    Serial.println((int)status);

    // If the controller is already idle, nothing to do.
    if (status == ESP_BT_CONTROLLER_STATUS_IDLE) {
        return;
    }

    if (status == ESP_BT_CONTROLLER_STATUS_ENABLED) {
        Serial.println("[BLE] Disabling BT controller before NimBLE init");
        esp_bt_controller_disable();
    }

    // After disable, or if it was just INITED, deinit to return to IDLE.
    if (status == ESP_BT_CONTROLLER_STATUS_ENABLED ||
        status == ESP_BT_CONTROLLER_STATUS_INITED) {
        Serial.println("[BLE] Deinitializing BT controller to return to IDLE");
        esp_bt_controller_deinit();
    }
}

class BleServerCallbacks : public NimBLEServerCallbacks {
    // Detailed connect callback with connection description.
    void onConnect(NimBLEServer* pServer, ble_gap_conn_desc* desc) override {
        (void)pServer;
        g_bleConnected = true;

        Serial.print("[BLE] Central connected, handle=");
        Serial.print(desc ? desc->conn_handle : -1);
        Serial.print(", peer=");
        if (desc) {
            Serial.println(NimBLEAddress(desc->peer_id_addr.val).toString().c_str());
        } else {
            Serial.println("<unknown>");
        }
    }

    // Detailed disconnect callback with connection description.
    void onDisconnect(NimBLEServer* pServer, ble_gap_conn_desc* desc) override {
        (void)pServer;
        g_bleConnected = false;

        Serial.print("[BLE] Central disconnected, handle=");
        Serial.print(desc ? desc->conn_handle : -1);
        Serial.print(", peer=");
        if (desc) {
            Serial.println(NimBLEAddress(desc->peer_id_addr.val).toString().c_str());
        } else {
            Serial.println("<unknown>");
        }
        Serial.println("[BLE] Resuming advertising");
        // Resume advertising so another host can connect.
        NimBLEDevice::startAdvertising();
    }

    // Return the passkey to use for pairing. The NimBLE default returns a
    // hardcoded 123456, which would never match the PIN we show on screen.
    uint32_t onPassKeyRequest() override {
        Serial.println("[BLE] onPassKeyRequest -> " + String(g_currentPasskey));
        return g_currentPasskey;
    }

    // Numeric-comparison / passkey confirmation. Accept the pairing request.
    bool onConfirmPIN(uint32_t pin) override {
        Serial.println("[BLE] onConfirmPIN: " + String(pin));
        return true;
    }

    void onAuthenticationComplete(ble_gap_conn_desc* desc) override {
        if (!desc) {
            Serial.println("[BLE] onAuthenticationComplete called with null desc");
            return;
        }

        Serial.print("[BLE] Auth complete for conn_handle=");
        Serial.print(desc->conn_handle);
        Serial.print(", peer=");
        Serial.println(NimBLEAddress(desc->peer_id_addr.val).toString().c_str());

        Serial.print("[BLE]   sec_state: encrypted=");
        Serial.print(desc->sec_state.encrypted);
        Serial.print(" authenticated=");
        Serial.print(desc->sec_state.authenticated);
        Serial.print(" bonded=");
        Serial.print(desc->sec_state.bonded);
        Serial.print(" key_size=");
        Serial.println(desc->sec_state.key_size);

        if (desc->sec_state.encrypted) {
            Serial.println("[BLE] Pairing successful (encrypted link established)");
        } else {
            Serial.println("[BLE] Pairing FAILED (link not encrypted)");
        }
    }
};

class BleRxCallbacks : public NimBLECharacteristicCallbacks {
    void onWrite(NimBLECharacteristic* pCharacteristic) override {
        std::string value = pCharacteristic->getValue();
        Serial.print("[BLE] RX write, len=");
        Serial.println((int)value.size());

        g_lastRxActivityMs = millis();

        for (char c : value) {
            if (c == '\n') {
                if (g_rxLineBuffer.length() > 0) {
                    Serial.print("[BLE] RX complete line, len=");
                    Serial.println(g_rxLineBuffer.length());
                    g_pendingLines.push_back(g_rxLineBuffer);
                    g_rxLineBuffer = "";
                }
            } else if (c != '\r') {
                g_rxLineBuffer += c;
            }
        }
    }
};

BluetoothManager::BluetoothManager()
    : started(false), lastConnected(false), lineBuffer(""), currentPin("") {}

void BluetoothManager::begin() {
    if (started) {
        return;
    }

    // Use a human-friendly name that includes the last 4 characters of the
    // pad UUID so multiple pads can be distinguished when pairing.
    String uuid = storage.getPadUUID();
    String suffix = uuid.length() >= 4 ? uuid.substring(uuid.length() - 4) : uuid;
    String devName = String("PAD-") + suffix;

    // Make sure the BT controller is not already initialized by any previous
    // stack before handing it to NimBLE.
    ensureBtControllerIdle();

    NimBLEDevice::init(devName.c_str());

    // Configure security to require a 6-digit passkey and create a bond. The
    // actual passkey value is provided later by startPairingSession() when
    // the user explicitly opens the Bluetooth Pairing screen.
    NimBLEDevice::setSecurityAuth(true, true, true);  // bonding, MITM, secure connections
    NimBLEDevice::setSecurityIOCap(BLE_HS_IO_DISPLAY_ONLY);

    // Ensure both sides exchange encryption and identity keys so a proper bond
    // can be stored. Without this, some centrals may complete an encrypted
    // session without actually persisting a bond.
    NimBLEDevice::setSecurityInitKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);
    NimBLEDevice::setSecurityRespKey(BLE_SM_PAIR_KEY_DIST_ENC | BLE_SM_PAIR_KEY_DIST_ID);
    Serial.println("[BLE] Security configured: bonding+MITM+SC, key dist ENC|ID");

    g_bleServer = NimBLEDevice::createServer();
    g_bleServer->setCallbacks(new BleServerCallbacks());

    g_bleService = g_bleServer->createService(DP_BLE_SERVICE_UUID);

    // TX characteristic: pad -> host, JSON lines via notifications or
    // indications. We enable indications so large multi-chunk payloads such
    // as pad_status are delivered reliably and in order.
    g_bleCharTx = g_bleService->createCharacteristic(
        DP_BLE_CHAR_TX_UUID,
        NIMBLE_PROPERTY::READ | NIMBLE_PROPERTY::NOTIFY | NIMBLE_PROPERTY::INDICATE);

    // RX characteristic: host -> pad, JSON lines written by the host.
    g_bleCharRx = g_bleService->createCharacteristic(
        DP_BLE_CHAR_RX_UUID,
        NIMBLE_PROPERTY::WRITE | NIMBLE_PROPERTY::WRITE_NR);
    g_bleCharRx->setCallbacks(new BleRxCallbacks());

    g_bleService->start();

    NimBLEAdvertising* advertising = NimBLEDevice::getAdvertising();
    advertising->addServiceUUID(DP_BLE_SERVICE_UUID);
    advertising->setScanResponse(true);
    advertising->start();

    started = true;
}

void BluetoothManager::loop() {
    if (!started) {
        return;
    }

    bool connected = g_bleConnected;

    if (!connected && lastConnected) {
        g_txQueue.clear();
        g_txActiveLine = "";
        g_txActiveOffset = 0;
        g_nextTxChunkAtMs = 0;
    }

    // Detect a new connection and send a hello JSON so the host bridge can
    // associate this link with a specific pad UUID.
    if (connected && !lastConnected) {
        JsonDocument doc;
        doc["type"] = "hello";
        doc["pad_uuid"] = storage.getPadUUID();
        doc["fw_version"] = String(FW_VERSION);

        String payload;
        serializeJson(doc, payload);
        sendJsonLine(payload);
    }

    if (connected && g_bleCharTx != nullptr) {
        unsigned long nowMs = millis();
        if (g_txActiveLine.length() == 0 && !g_txQueue.empty()) {
            g_txActiveLine = g_txQueue.front();
            g_txQueue.pop_front();
            g_txActiveOffset = 0;
            g_nextTxChunkAtMs = 0;
        }

        if (g_txActiveLine.length() > 0 &&
            (g_nextTxChunkAtMs == 0 || (long)(nowMs - g_nextTxChunkAtMs) >= 0)) {
            const char* raw = g_txActiveLine.c_str();
            size_t totalLen = g_txActiveLine.length();
            size_t chunkLen = totalLen - g_txActiveOffset;
            if (chunkLen > BLE_NOTIFY_CHUNK_SIZE) {
                chunkLen = BLE_NOTIFY_CHUNK_SIZE;
            }

            g_bleCharTx->setValue((const uint8_t*)(raw + g_txActiveOffset), chunkLen);
            g_bleCharTx->indicate();
            g_lastTxActivityMs = nowMs;
            g_txActiveOffset += chunkLen;

            if (g_txActiveOffset >= totalLen) {
                g_txActiveLine = "";
                g_txActiveOffset = 0;
                g_nextTxChunkAtMs = 0;
            } else {
                g_nextTxChunkAtMs = nowMs + 8;
            }
        }
    }

    lastConnected = connected;
}

bool BluetoothManager::isConnected() const {
    if (!started) {
        return false;
    }
    return g_bleConnected;
}

bool BluetoothManager::sendJsonLine(const String& line) {
    if (!isConnected() || g_bleCharTx == nullptr) {
        return false;
    }

    g_txQueue.push_back(line + "\n");
    return true;
}

unsigned long BluetoothManager::getLastRxActivityMs() const {
    return g_lastRxActivityMs;
}

unsigned long BluetoothManager::getLastTxActivityMs() const {
    return g_lastTxActivityMs;
}

void BluetoothManager::drainPendingLines(std::vector<String>& out) {
    out.insert(out.end(), g_pendingLines.begin(), g_pendingLines.end());
    g_pendingLines.clear();
}

String BluetoothManager::startPairingSession() {
    // Generate a random 6-digit PIN (000000-999999).
    char buf[7];
    unsigned long val = (unsigned long)random(0, 1000000UL);
    snprintf(buf, sizeof(buf), "%06lu", val);
    currentPin = String(buf);

    // Apply the PIN to the NimBLE security configuration so that hosts must
    // enter this code when pairing. We also store it in g_currentPasskey so
    // the BleServerCallbacks::onPassKeyRequest() callback returns this exact
    // value (the NimBLE default would otherwise return a hardcoded 123456).
    uint32_t pinValue = (uint32_t)currentPin.toInt();
    g_currentPasskey = pinValue;
    Serial.print("[BLE] New pairing PIN generated: ");
    Serial.println(currentPin);
    Serial.print("[BLE] Applying passkey to NimBLEDevice: ");
    Serial.println(pinValue);
    NimBLEDevice::setSecurityPasskey(pinValue);

    return currentPin;
}

String BluetoothManager::getCurrentPin() const {
    return currentPin;
}

void BluetoothManager::clearBonds() {
    if (!started) {
        return;
    }
    Serial.println("[BLE] Clearing all stored bonds for fresh pairing");
    NimBLEDevice::deleteAllBonds();
}
