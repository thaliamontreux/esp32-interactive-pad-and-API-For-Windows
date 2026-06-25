/*
 * DisplayPad ESP32 Firmware
 *
 * Hardware: ESP32-WROOM-32 + ILI9341 240x320 Touch Display
 * Framework: Arduino with PlatformIO
 *
 * Features:
 * - WiFi setup with AP mode
 * - Secure NVS storage
 * - Touch-based PIN keypad
 * - API pairing and discovery
 * - WebSocket real-time updates
 * - Button rendering and press handling
 * - Control panel with diagnostics
 */

#include <Arduino.h>
#include <ArduinoJson.h>
#include <sys/time.h>
#include "config.h"
#include "storage.h"
#include "display.h"
#include "wifi_manager.h"
#include "bluetooth_manager.h"
#include "pin_keypad.h"
#include "text_keyboard.h"
#include "ip_keyboard.h"
#include "api_client.h"
#include "button_renderer.h"
#include "control_panel.h"
#include "discovery_beacon.h"
#include "icon_cache.h"
#include "connection_mode.h"
#include "startup_wav.h"

// State machine
enum class AppState {
    BOOT,
    STARTUP_WINDOW,
    WIFI_SETUP,
    LAST_SERVER_CONNECT,  // Try last known API IP before full network scan
    DISCOVERY_WAITING,    // Waiting for server to assign us (via beacon)
    NORMAL_OPERATION,
    CONTROL_PANEL,
    ERROR
};

AppState currentState = AppState::BOOT;
unsigned long stateStartTime = 0;
bool configLoaded = false;
bool buttonsDirty = true;  // track when button UI needs a full re-render
PadConfig currentConfig;

// Track periodic time updates so the topbar clock stays fresh and can
// periodically resync from the host.
static int g_lastDrawnMinute = -1;
static unsigned long g_lastTimeSyncMs = 0;

// Track whether the host display is currently considered locked. When true,
// we keep showing the lock screen image and suppress normal button rendering
// until an explicit host_display_state=unlocked message is received.
bool g_hostDisplayLocked = false;

const uint8_t AUDIO_ENABLE_PIN = 4;

// Per-boot logging session so the API can group raw console logs by device
// reboot. We generate a simple UUID-like token at startup and attach a
// monotonically increasing sequence number to each log line.
String g_logSessionUUID;
uint32_t g_logSeq = 0;

// Forward declarations
void enterState(AppState newState);
void handleBoot();
void handleStartupWindow();
void handleWiFiSetup();
void handleLastServerConnect();
void handleDiscoveryWaiting();
void handleNormalOperation();
void handleControlPanel();
void handleError();
bool loadConfigFromAPI();
bool loadConfigFromBLE();
void pairingScreen();
void pairingScreenLegacy();
void showError(const String& message);
void showConnectionFailedPopup();
void requestCurrentHostSessionState();
void sendPadStatusSnapshot();
bool scanForServerAtIP(const String& ip);

static String generateLogSessionUUID() {
    // Simple session UUID based on pad UUID and current millis; this does not
    // need to be cryptographically strong, just unique per boot.
    String base = storage.getPadUUID();
    base.replace("-", "");
    char buf[16];
    snprintf(buf, sizeof(buf), "%08lx", (unsigned long)millis());
    return base + "_" + String(buf);
}

void sendPadStatusSnapshot() {
    ConnectionMode mode = getConnectionMode();
    bool bleActive = (mode == ConnectionMode::BLUETOOTH) ||
                     (mode == ConnectionMode::AUTO && btManager.isConnected());
    bool wifiActive = (mode != ConnectionMode::BLUETOOTH);
    time_t nowEpoch = time(nullptr);

    if (bleActive && configLoaded) {
        JsonDocument bleDoc;
        bleDoc["type"] = "pad_status";
        bleDoc["pad_uuid"] = storage.getPadUUID();
        bleDoc["fw_version"] = String(FW_VERSION);
        bleDoc["config_version"] = storage.getConfigVersion();
        bleDoc["pad_mode"] = buttonRenderer.getIsTaskKeypadMode() ? "task_keypad" : "macro_keypad";
        bleDoc["current_page"] = buttonRenderer.getCurrentPage();
        bleDoc["page_count"] = buttonRenderer.getTotalPages();
        bleDoc["host_locked"] = g_hostDisplayLocked;
        bleDoc["config_loaded"] = configLoaded;
        bleDoc["buttons_dirty"] = buttonsDirty;
        bleDoc["connection_mode"] = static_cast<int>(mode);
        bleDoc["wifi_connected"] = (WiFi.status() == WL_CONNECTED);
        bleDoc["api_connected"] = apiClient.isWebSocketConnected();
        bleDoc["ble_connected"] = btManager.isConnected();
        if (nowEpoch > 0) {
            bleDoc["epoch"] = static_cast<long>(nowEpoch);
        }

        JsonArray blePressedSlots = bleDoc["pressed_slots"].to<JsonArray>();
        for (int slot : buttonRenderer.getPressedSlots()) {
            blePressedSlots.add(slot);
        }

        JsonArray bleActiveTaskSlots = bleDoc["active_task_slots"].to<JsonArray>();
        for (int slot : buttonRenderer.getActiveTaskSlots()) {
            bleActiveTaskSlots.add(slot);
        }

        String blePayload;
        serializeJson(bleDoc, blePayload);
        btManager.sendJsonLine(blePayload);
    }

    if (wifiActive) {
        JsonDocument wifiDoc;
        wifiDoc["type"] = "pad_status";
        wifiDoc["pad_uuid"] = storage.getPadUUID();
        wifiDoc["fw_version"] = String(FW_VERSION);
        wifiDoc["config_version"] = storage.getConfigVersion();
        wifiDoc["pad_mode"] = buttonRenderer.getIsTaskKeypadMode() ? "task_keypad" : "macro_keypad";
        wifiDoc["current_page"] = buttonRenderer.getCurrentPage();
        wifiDoc["page_count"] = buttonRenderer.getTotalPages();
        wifiDoc["host_locked"] = g_hostDisplayLocked;
        wifiDoc["config_loaded"] = configLoaded;
        wifiDoc["buttons_dirty"] = buttonsDirty;
        wifiDoc["connection_mode"] = static_cast<int>(mode);
        wifiDoc["wifi_connected"] = (WiFi.status() == WL_CONNECTED);
        wifiDoc["api_connected"] = apiClient.isWebSocketConnected();
        wifiDoc["ble_connected"] = btManager.isConnected();
        wifiDoc["api_host"] = storage.getApiHost();
        wifiDoc["api_ip"] = storage.getApiIP();
        wifiDoc["api_port"] = storage.getApiPort();
        wifiDoc["api_uuid"] = storage.getApiUUID();
        if (nowEpoch > 0) {
            wifiDoc["epoch"] = static_cast<long>(nowEpoch);
            struct tm* timeInfo = gmtime(&nowEpoch);
            if (timeInfo != nullptr) {
                char timeBuf[16];
                char dateBuf[16];
                strftime(timeBuf, sizeof(timeBuf), "%H:%M:%S", timeInfo);
                strftime(dateBuf, sizeof(dateBuf), "%Y-%m-%d", timeInfo);
                wifiDoc["time_text"] = String(timeBuf);
                wifiDoc["date_text"] = String(dateBuf);
            }
        }

        JsonArray wifiPressedSlots = wifiDoc["pressed_slots"].to<JsonArray>();
        for (int slot : buttonRenderer.getPressedSlots()) {
            wifiPressedSlots.add(slot);
        }

        JsonArray wifiActiveTaskSlots = wifiDoc["active_task_slots"].to<JsonArray>();
        for (int slot : buttonRenderer.getActiveTaskSlots()) {
            wifiActiveTaskSlots.add(slot);
        }

        String wifiPayload;
        serializeJson(wifiDoc, wifiPayload);
        apiClient.sendPadStatus(wifiPayload);
    }
}

// Simple helper for mirroring important log lines both to the serial console
// and to the DisplayPad API (when connected). This avoids spamming the
// network with every low-level debug print while still capturing the
// high-level lifecycle events needed for remote diagnostics.
#define DP_LOG(msg)                          \
    do {                                     \
        Serial.println(msg);                 \
        apiClient.sendLogLine(g_logSessionUUID, g_logSeq++, msg); \
    } while (0)

ConnectionMode getConnectionMode() {
    uint8_t raw = storage.getConnectionMode();
    switch (raw) {
        case 0: return ConnectionMode::WIFI;
        case 1: return ConnectionMode::BLUETOOTH;
        case 2: default: return ConnectionMode::AUTO;
    }
}

void setConnectionMode(ConnectionMode mode) {
    storage.setConnectionMode(static_cast<uint8_t>(mode));
}

// Play the embedded startup.wav over the on-board speaker on GPIO 26.
// The WAV file is expected to be 8-bit mono PCM. We parse a minimal
// RIFF/WAVE header to locate the data chunk and sample rate, then stream
// samples using dacWrite(). This is a blocking call intended for a short
// boot jingle.
static void playStartupSoundOnce() {
    DP_LOG("[Audio] playStartupSoundOnce: StartupWavSize=" + String(StartupWavSize));
    if (StartupWavSize < 44) {
        DP_LOG("[Audio] Startup WAV too small to be valid, skipping playback");
        return;  // too small to be a valid WAV
    }

    const uint8_t* data = StartupWav;
    const uint8_t* end = StartupWav + StartupWavSize;

    // Check RIFF/WAVE header
    if (memcmp(data, "RIFF", 4) != 0 || memcmp(data + 8, "WAVE", 4) != 0) {
        DP_LOG("[Audio] Invalid RIFF/WAVE header, skipping playback");
        return;
    }

    // Walk chunks to find "fmt " and "data"
    const uint8_t* p = data + 12;  // first chunk after RIFF header
    uint32_t sampleRate = 8000;    // safe default
    uint16_t bitsPerSample = 8;
    uint16_t numChannels = 1;
    const uint8_t* dataStart = nullptr;
    uint32_t dataSize = 0;

    while (p + 8 <= end) {
        uint32_t chunkId = *(const uint32_t*)p;
        uint32_t chunkSize = *(const uint32_t*)(p + 4);
        const uint8_t* chunkData = p + 8;
        if (chunkData + chunkSize > end) {
            DP_LOG("[Audio] WAV chunk exceeds buffer, aborting playback");
            break;
        }

        if (chunkId == 0x20746d66) {  // 'fmt '
            if (chunkSize >= 16) {
                uint16_t audioFormat = *(const uint16_t*)(chunkData + 0);
                numChannels = *(const uint16_t*)(chunkData + 2);
                sampleRate = *(const uint32_t*)(chunkData + 4);
                bitsPerSample = *(const uint16_t*)(chunkData + 14);
                DP_LOG("[Audio] WAV fmt chunk: format=" + String(audioFormat) +
                       ", channels=" + String(numChannels) +
                       ", sampleRate=" + String(sampleRate) +
                       ", bitsPerSample=" + String(bitsPerSample));
                if (audioFormat != 1 || numChannels != 1 || bitsPerSample != 8) {
                    DP_LOG("[Audio] Unsupported WAV format (need 8-bit mono PCM), skipping playback");
                    // Only support 8-bit mono PCM
                    return;
                }
            }
        } else if (chunkId == 0x61746164) {  // 'data'
            dataStart = chunkData;
            dataSize = chunkSize;
            DP_LOG("[Audio] WAV data chunk found, size=" + String(dataSize));
            break;
        }

        // Chunks are padded to even sizes
        uint32_t advance = 8 + chunkSize;
        if (advance & 1) advance++;
        p += advance;
    }

    if (!dataStart || dataSize == 0) {
        DP_LOG("[Audio] No WAV data chunk found, skipping playback");
        return;
    }

    // Basic timing for sample playback
    if (sampleRate == 0) {
        sampleRate = 8000;
    }
    uint32_t usPerSample = 1000000UL / sampleRate;
    DP_LOG("[Audio] Playing startup WAV: sampleRate=" + String(sampleRate) +
           ", usPerSample=" + String(usPerSample) +
           ", dataSize=" + String(dataSize));

    const uint8_t* s = dataStart;
    const uint8_t* sEnd = dataStart + dataSize;
    if (sEnd > end) sEnd = end;

    const uint8_t kDacPin = 26;
    while (s < sEnd) {
        uint8_t v = *s++;
        int16_t centered = (int16_t)v - 128;
        centered *= 3;  // strong gain to drive full DAC range
        if (centered > 127) centered = 127;
        if (centered < -128) centered = -128;
        uint8_t boosted = (uint8_t)(centered + 128);
        dacWrite(kDacPin, boosted);
        delayMicroseconds(usPerSample);
    }
    DP_LOG("[Audio] Startup WAV playback complete");
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    DP_LOG("\n=== DisplayPad ESP32 Starting ===");

    pinMode(AUDIO_ENABLE_PIN, OUTPUT);
    digitalWrite(AUDIO_ENABLE_PIN, LOW);

    // Initialize NVS storage
    if (!storage.begin()) {
        DP_LOG("Failed to initialize storage!");
        showError("Storage Error");
        return;
    }

    // Generate pad profile if first boot
    if (storage.getPadUUID().length() == 0) {
        DP_LOG("First boot - generating pad profile...");
        storage.generateNewProfile();
    }

    DP_LOG("Pad UUID: " + storage.getPadUUID());

    // Initialize display
    if (!display.begin()) {
        DP_LOG("Failed to initialize display!");
        showError("Display Error");
        return;
    }
    DP_LOG("Display initialized");

    // Initialize icon cache filesystem
    iconCache.begin();

    // Initialize other modules
    pinKeypad.begin();
    buttonRenderer.begin();
    controlPanel.begin();

    // Show the embedded logo once during startup so the pad displays the
    // Penta Star Studios splash screen while it is booting and connecting.
    buttonRenderer.showHostLockScreen();

    // Play the startup sound once over the speaker on GPIO 26, if the
    // embedded startup.wav data is present and valid.
    playStartupSoundOnce();

    // Initialize Bluetooth SPP service (non-blocking). This does not change
    // existing WiFi behavior; it simply makes the pad discoverable as a
    // Bluetooth serial device that we will use for an alternate host
    // transport in a later step.
    btManager.begin();

    // Initialize per-boot log session. We will notify the API about this
    // session once the WebSocket connection is established in
    // loadConfigFromAPI().
    g_logSessionUUID = generateLogSessionUUID();
    g_logSeq = 0;

    // Start in boot state
    enterState(AppState::BOOT);
}

void loop() {
    ConnectionMode mode = getConnectionMode();

    if (mode != ConnectionMode::BLUETOOTH) {
        // In WiFi and AUTO modes we keep the WiFi manager, API client, and
        // discovery beacon running as before.
        wifiManager.loop();
        apiClient.loop();
        discovery.loop();
    }

    // Always service the Bluetooth manager so BLE transport remains
    // responsive regardless of mode.
    btManager.loop();

    // Handle button press feedback timeout
    buttonRenderer.clearFeedback();

    static unsigned long lastPadStatusMs = 0;
    unsigned long padStatusIntervalMs = ((mode == ConnectionMode::BLUETOOTH) ||
                                         (mode == ConnectionMode::AUTO && btManager.isConnected()))
                                            ? 15000
                                            : 5000;
    if (millis() - lastPadStatusMs >= padStatusIntervalMs) {
        lastPadStatusMs = millis();
        sendPadStatusSnapshot();
    }

    // State machine
    switch (currentState) {
        case AppState::BOOT:
            handleBoot();
            break;
        case AppState::STARTUP_WINDOW:
            handleStartupWindow();
            break;
        case AppState::WIFI_SETUP:
            handleWiFiSetup();
            break;
        case AppState::LAST_SERVER_CONNECT:
            handleLastServerConnect();
            break;
        case AppState::DISCOVERY_WAITING:
            handleDiscoveryWaiting();
            break;
        case AppState::NORMAL_OPERATION:
            handleNormalOperation();
            break;
        case AppState::CONTROL_PANEL:
            handleControlPanel();
            break;
        case AppState::ERROR:
            handleError();
            break;
    }

    delay(10);
}

void enterState(AppState newState) {
    currentState = newState;
    stateStartTime = millis();
    Serial.print("Entering state: ");
    Serial.println((int)newState);
}

void handleBoot() {
    ConnectionMode mode = getConnectionMode();

    // In pure Bluetooth mode we skip WiFi and the startup window and go
    // directly to normal operation, where the pad will wait for the BLE
    // bridge and load its config over Bluetooth.
    if (mode == ConnectionMode::BLUETOOTH) {
        enterState(AppState::NORMAL_OPERATION);
        return;
    }

    // Check if WiFi is configured
    String ssid = storage.getWiFiSSID();

    if (ssid.length() == 0) {
        // No WiFi config - show startup window then WiFi setup
        enterState(AppState::STARTUP_WINDOW);
    } else {
        // Try to connect to saved WiFi
        DP_LOG("Connecting to saved WiFi: " + ssid);

        extern DisplayManager display;
        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_CYAN, COLOR_BLACK);
        display.drawCentreString("Connecting to WiFi...", SCREEN_WIDTH/2, 40);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString(ssid, SCREEN_WIDTH/2, 80);
        display.drawCentreString("Please wait...", SCREEN_WIDTH/2, 100);

        wifiManager.begin();

        if (wifiManager.isConnected()) {
            DP_LOG("WiFi connected: " + wifiManager.getIP());

            // If we have a stored API IP from a previous successful pairing, try
            // to talk to that server first for up to 5 minutes before doing a
            // full subnet scan.
            String lastApiIp = storage.getApiIP();
            if (storage.isPaired() && lastApiIp.length() > 0) {
                DP_LOG("[Boot] Found stored API IP: " + lastApiIp +
                       " - trying direct connection before discovery scan");
                enterState(AppState::LAST_SERVER_CONNECT);
            } else {
                // No stored server - fall back to discovery scanning immediately.
                DP_LOG("[Boot] WiFi OK - starting discovery scan for host");
                discovery.begin();
                enterState(AppState::DISCOVERY_WAITING);
            }
        } else {
            // WiFi connection failed
            DP_LOG("WiFi connection failed");
            enterState(AppState::WIFI_SETUP);
        }
    }
}

void handleStartupWindow() {
    // Show 20-second startup window with option to enter control panel
    bool enteredControlPanel = controlPanel.showStartupWindow();

    if (enteredControlPanel) {
        enterState(AppState::CONTROL_PANEL);
    } else {
        // Window expired with no interaction: proceed to normal operation so
        // the pad can attempt to load its buttons/config instead of dropping
        // into the control panel.
        enterState(AppState::NORMAL_OPERATION);
    }
}

void handleWiFiSetup() {
    // Use the on-device WiFi configuration screen instead of instructing the
    // user to connect to an AP and open a browser.
    controlPanel.showWiFiSetup();

    if (!wifiManager.isConnected()) {
        // User backed out or connection failed; return to control panel or
        // discovery based on pairing status.
        if (storage.isPaired()) {
            enterState(AppState::CONTROL_PANEL);
        } else {
            enterState(AppState::DISCOVERY_WAITING);
        }
        return;
    }

    // WiFi connected; proceed as we did after the old AP-based setup.
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
    display.drawCentreString("Connected!", SCREEN_WIDTH/2, 100);
    delay(2000);

    // After WiFi setup, prefer trying the last known API IP (if any) for a
    // few minutes before falling back to a full discovery scan.
    String lastApiIp = storage.getApiIP();
    if (storage.isPaired() && lastApiIp.length() > 0) {
        DP_LOG("[WiFiSetup] Found stored API IP: " + lastApiIp +
               " - trying direct connection before discovery scan");
        enterState(AppState::LAST_SERVER_CONNECT);
    } else {
        DP_LOG("[Boot] Starting network scan for DisplayPad Server...");
        discovery.begin();
        enterState(AppState::DISCOVERY_WAITING);
    }
}

void handleDiscoveryWaiting() {
    static bool firstRun = true;
    static unsigned long startTime = 0;
    static String currentServerIP = "";

    if (firstRun) {
        display.clear();
        firstRun = false;
        startTime = millis();
        currentServerIP = "";
        DP_LOG("[Discovery] Starting aggressive network scan for port 7443...");
    }

    // Check if assigned via UDP
    if (discovery.isAssigned()) {
        DP_LOG("[Discovery] Assigned! Moving to normal operation");
        firstRun = true;
        enterState(AppState::NORMAL_OPERATION);
        return;
    }

    // If we don't yet have a server IP, scan the subnet for one
    if (currentServerIP.length() == 0) {
        // Get subnet
        String localIP = WiFi.localIP().toString();
        int lastDot = localIP.lastIndexOf('.');
        String subnet = localIP.substring(0, lastDot + 1);

        // Aggressively scan ALL IPs 1-254
        int myLastOctet = localIP.substring(lastDot + 1).toInt();

        for (int i = 1; i <= 254; i++) {
            if (i == myLastOctet) continue;  // skip our own IP

            String testIP = subnet + String(i);
            Serial.print("[Scan] Trying " + testIP + ":7443 ... ");

            // Use helper which sends hello + auto-assign and returns true on success
            if (scanForServerAtIP(testIP)) {
                currentServerIP = testIP;

                // Draw status for found server
                display.fillRect(20, 80, SCREEN_WIDTH - 40, 50, COLOR_BLACK);
                display.setTextSize(1);
                display.setTextColor(COLOR_GREEN, COLOR_BLACK);
                display.drawCentreString("Found host: " + testIP, SCREEN_WIDTH/2, 85);

                Serial.println("[Discovery] Host " + testIP + " contacted, waiting for assignment...");
                break;  // stop scanning further IPs once we have a host
            } else {
                Serial.println("no response");
            }

            // Update display occasionally (every 10 IPs)
            if (i % 10 == 0) {
                display.fillRect(20, 80, SCREEN_WIDTH - 40, 50, COLOR_BLACK);
                display.setTextSize(1);
                display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                display.drawCentreString("Scanning: " + subnet + "* (" + String(i) + "/254)", SCREEN_WIDTH/2, 85);
            }

            delay(50);  // brief delay between scans
        }

        Serial.println("[Discovery] Subnet scan pass complete");
    }

    // Draw status
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_CYAN, COLOR_BLACK);
    display.drawCentreString("Scanning Network...", SCREEN_WIDTH/2, 40);

    // Show UUID
    String uuid = storage.getPadUUID();
    display.setTextSize(1);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    if (uuid.length() > 20) {
        display.drawCentreString(uuid.substring(0, 20), SCREEN_WIDTH/2, 100);
        display.drawCentreString(uuid.substring(20), SCREEN_WIDTH/2, 112);
    } else {
        display.drawCentreString(uuid, SCREEN_WIDTH/2, 106);
    }

    // Show scan progress or found status
    int elapsed = (millis() - startTime) / 1000;
    display.setTextColor(COLOR_GRAY, COLOR_BLACK);
    if (currentServerIP.length() > 0) {
        display.drawCentreString("Hello sent to " + currentServerIP, SCREEN_WIDTH/2, 140);
        display.drawCentreString("Waiting for assignment...", SCREEN_WIDTH/2, 155);
    } else {
        display.drawCentreString("Scanning: " + String(elapsed) + "s", SCREEN_WIDTH/2, 140);
    }

    // Manual setup is no longer used; discovery/auto-assign handles all provisioning.
}

bool scanForServerAtIP(const String& ip) {
    // Quick TCP check - try to connect to API port
    WiFiClient client;
    if (!client.connect(ip.c_str(), DEFAULT_API_PORT)) {
        return false;
    }

    // Server found! Send hello message
    Serial.println("[Scan] Found server at " + ip + ", sending hello...");

    // Build JSON hello message
    String uuid = storage.getPadUUID();
    String mac = WiFi.macAddress();

    String jsonBody = "{";
    jsonBody += "\"uuid\":\"" + uuid + "\",";
    jsonBody += "\"mac\":\"" + mac + "\",";
    jsonBody += "\"screen_width\":" + String(SCREEN_WIDTH) + ",";
    jsonBody += "\"screen_height\":" + String(SCREEN_HEIGHT) + ",";
    jsonBody += "\"button_count\":6";
    jsonBody += "}";

    // Send HTTP POST
    client.print("POST /api/v1/discovery/hello HTTP/1.1\r\n");
    client.print("Host: " + ip + "\r\n");
    client.print("Content-Type: application/json\r\n");
    client.print("Content-Length: " + String(jsonBody.length()) + "\r\n");
    client.print("Connection: close\r\n");
    client.print("\r\n");
    client.print(jsonBody);

    // Read response
    unsigned long timeout = millis() + 5000;
    bool accepted = false;
    while (client.connected() && millis() < timeout) {
        if (client.available()) {
            String line = client.readStringUntil('\n');
            if (line.indexOf("200 OK") > 0) {
                Serial.println("[Scan] Hello accepted by server");
                accepted = true;
                break;
            }
        }
        delay(10);
    }

    client.stop();

    // If hello was accepted, auto-request assignment
    if (accepted) {
        delay(100);
        WiFiClient assignClient;
        if (assignClient.connect(ip.c_str(), DEFAULT_API_PORT)) {
            String assignBody = "{";
            assignBody += "\"uuid\":\"" + uuid + "\",";
            assignBody += "\"name\":\"AutoPad-" + uuid.substring(0, 8) + "\",";
            assignBody += "\"mode\":\"macro_keypad\"";
            assignBody += "}";

            assignClient.print("POST /api/v1/discovery/assign HTTP/1.1\r\n");
            assignClient.print("Host: " + ip + "\r\n");
            assignClient.print("Content-Type: application/json\r\n");
            assignClient.print("Content-Length: " + String(assignBody.length()) + "\r\n");
            assignClient.print("Connection: close\r\n");
            assignClient.print("\r\n");
            assignClient.print(assignBody);

            Serial.println("[Scan] Auto-assignment requested");
            delay(100);
            assignClient.stop();
        }
        return true;
    }

    return false;
}

void pairingScreenLegacy() {
    // Legacy pairing screen - kept for reference
    // This function is no longer used
}

void handleNormalOperation() {
    ConnectionMode mode = getConnectionMode();

    // Detect a new active BLE connection (in BLUETOOTH or AUTO+BLE mode) and
    // force a fresh config load when this happens so we never rely on stale
    // data from a previous session.
    static bool lastBleActive = false;
    static bool configUpdateRequested = false;
    static unsigned long nextBleConfigRetryMs = 0;
    static uint16_t bleRetryCountdownSeconds = 0;
    bool bleActiveNow = (mode == ConnectionMode::BLUETOOTH) ||
                        (mode == ConnectionMode::AUTO && btManager.isConnected());
    if (bleActiveNow && !lastBleActive) {
        Serial.println("[Main] BLE became active - forcing config reload");
        configLoaded = false;
        buttonsDirty = true;
    }
    lastBleActive = bleActiveNow;

    // Load config if not loaded
    if (!configLoaded) {
        bool ok = false;
        unsigned long nowMs = millis();

        bool preferBLE = (mode == ConnectionMode::BLUETOOTH) ||
                          (mode == ConnectionMode::AUTO && btManager.isConnected());

        if (preferBLE) {
            if (nextBleConfigRetryMs != 0 && (long)(nowMs - nextBleConfigRetryMs) < 0) {
                unsigned long remainingMs = nextBleConfigRetryMs - nowMs;
                uint16_t sec = (remainingMs + 999) / 1000;
                if (sec != bleRetryCountdownSeconds) {
                    bleRetryCountdownSeconds = sec;
                    extern DisplayManager display;
                    display.clear();
                    display.setTextSize(2);
                    display.setTextDatum(TC_DATUM);
                    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
                    display.drawCentreString("Waiting for buttons...", SCREEN_WIDTH/2, 40);
                    display.setTextSize(1);
                    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                    display.drawCentreString("No config from host yet.", SCREEN_WIDTH/2, 80);
                    display.drawCentreString("Retrying in " + String(sec) + "s", SCREEN_WIDTH/2, 100);
                }
                return;
            }

            Serial.println("[Main] Loading config via BLE (Bluetooth path)...");
            ok = loadConfigFromBLE();
            if (!ok) {
                const unsigned long RETRY_DELAY_MS = 10000;  // 10 seconds
                nextBleConfigRetryMs = nowMs + RETRY_DELAY_MS;
                bleRetryCountdownSeconds = RETRY_DELAY_MS / 1000;

                extern DisplayManager display;
                display.clear();
                display.setTextSize(2);
                display.setTextDatum(TC_DATUM);
                display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
                display.drawCentreString("Waiting for buttons...", SCREEN_WIDTH/2, 40);
                display.setTextSize(1);
                display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                display.drawCentreString("No config from host yet.", SCREEN_WIDTH/2, 80);
                display.drawCentreString("Retrying in " + String(bleRetryCountdownSeconds) + "s", SCREEN_WIDTH/2, 100);

                return;
            }
            nextBleConfigRetryMs = 0;
            bleRetryCountdownSeconds = 0;
        } else {
            if (mode == ConnectionMode::WIFI) {
                Serial.println("[Main] Loading config via WiFi API (WiFi mode)...");
                ok = loadConfigFromAPI();
            } else {
                Serial.println("[Main] AUTO mode: BLE not connected, loading via WiFi API...");
                ok = loadConfigFromAPI();
            }

            if (!ok) {
                Serial.println("[Main] Config load failed, going to ERROR");
                enterState(AppState::ERROR);
                return;
            }
        }

        Serial.println("[Main] Config loaded, buttons: " + String(buttonRenderer.getButtonCount()));
        // After a (re)load, force a fresh render once
        buttonsDirty = true;
        configUpdateRequested = false;
    }

    // In Bluetooth or AUTO+BLE mode, once config is loaded, keep consuming
    // any JSON messages that the host bridge sends over BLE (e.g. periodic
    // time updates or task_app_state messages for Task Keypad) and apply
    // them to the current runtime state.
    bool bleActive = (mode == ConnectionMode::BLUETOOTH) ||
                     (mode == ConnectionMode::AUTO && btManager.isConnected());
    if (bleActive && configLoaded) {
        std::vector<String> lines;
        btManager.drainPendingLines(lines);

        for (const String& line : lines) {
            JsonDocument doc;
            DeserializationError err = deserializeJson(doc, line);
            if (err) {
                continue;
            }

            String type = doc["type"].as<String>();
            if (type == "time") {
                long epoch = doc["epoch"] | 0;
                if (epoch > 0) {
                    struct timeval tv;
                    tv.tv_sec = epoch;
                    tv.tv_usec = 0;
                    settimeofday(&tv, nullptr);
                    Serial.print("[Time][BLE] Time set from host during NORMAL_OPERATION, epoch=");
                    Serial.println(epoch);
                }
            } else if (type == "config_update_pending") {
                configLoaded = false;
                buttonsDirty = true;
                return;
            } else if (type == "task_app_state") {
                JsonArray arr = doc["buttons"].as<JsonArray>();
                extern ButtonRenderer buttonRenderer;
                buttonRenderer.clearTaskAppState();

                // Track which slots are currently marked running so we can
                // acknowledge back to the host/bridge.
                std::vector<int> activeSlots;
                activeSlots.reserve(arr.size());

                for (JsonObject obj : arr) {
                    int slot = obj["slot"] | 0;
                    bool running = obj["running"] | false;
                    if (slot > 0 && running) {
                        buttonRenderer.setTaskAppRunning(slot, true);
                        activeSlots.push_back(slot);
                    }
                }

                extern bool buttonsDirty;
                buttonsDirty = true;

                // Send a lightweight ACK back to the BLE bridge so the
                // server can verify that this task_app_state was applied and
                // how many buttons are currently active on the pad.
                int version = doc["version"] | 0;
                extern SecureStorage storage;
                String padUUID = storage.getPadUUID();

                Serial.print("[Main] Applied task_app_state version=");
                Serial.print(version);
                Serial.print(" active_count=");
                Serial.println(activeSlots.size());
                Serial.print("[Main] Active task slots: ");
                for (size_t i = 0; i < activeSlots.size(); ++i) {
                    if (i > 0) {
                        Serial.print(",");
                    }
                    Serial.print(activeSlots[i]);
                }
                Serial.println();

                String ack = "{";
                ack += "\"type\":\"task_app_state_ack\",";
                ack += "\"pad_uuid\":\"" + padUUID + "\"";
                if (version > 0) {
                    ack += ",\"version\":" + String(version);
                }
                ack += ",\"active_slots\":[";
                bool first = true;
                for (int slot : activeSlots) {
                    if (!first) {
                        ack += ",";
                    }
                    ack += String(slot);
                    first = false;
                }
                ack += "]";
                ack += "}";

                btManager.sendJsonLine(ack);
            } else if (type == "host_display_state") {
                String state = doc["state"].as<String>();
                bool locked = (state == "locked");

                extern DisplayManager display;
                extern ButtonRenderer buttonRenderer;
                extern bool g_hostDisplayLocked;

                // Ensure backlight is on so the lock screen image is visible.
                display.setBacklight(true);

                if (locked) {
                    g_hostDisplayLocked = true;
                    Serial.println("[POWER] BLE: host_display_state=locked; showing lock screen");
                    buttonRenderer.showHostLockScreen();
                } else {
                    g_hostDisplayLocked = false;
                    Serial.println("[POWER] BLE: host_display_state=unlocked; refreshing buttons");
                    extern bool buttonsDirty;
                    buttonsDirty = true;
                }
            }
        }
    }

    // Render buttons only when something changed, and only when the host
    // display is not locked. While locked, we keep showing the lock screen
    // image and suppress normal keypad UI updates.
    if (!g_hostDisplayLocked && buttonsDirty) {
        Serial.println("[Main] Rendering buttons (dirty=true)...");
        buttonRenderer.forceRefresh();
        buttonsDirty = false;
    }

    // Ensure the topbar clock stays in sync visually by forcing a lightweight
    // refresh when the minute value changes. We only do this while in
    // NORMAL_OPERATION and after configuration has been loaded so that we
    // never redraw on top of splash / setup screens.
    if (!g_hostDisplayLocked && configLoaded) {
        time_t now = time(nullptr);
        if (now > 0) {
            struct tm* ti = gmtime(&now);
            if (ti) {
                int currentMinute = ti->tm_min;
                if (currentMinute != g_lastDrawnMinute) {
                    g_lastDrawnMinute = currentMinute;
                    buttonRenderer.drawTaskbar();
                }
            }
        }
    }

    // Periodically request a fresh time sync from the host so that long-
    // running sessions stay aligned. The host should interpret this as a
    // hint to send a current-time message over the active channel.
    unsigned long nowMs = millis();
    const unsigned long TIME_SYNC_INTERVAL_MS = 10UL * 60UL * 1000UL;  // 10 minutes
    if (configLoaded && !g_hostDisplayLocked &&
        (g_lastTimeSyncMs == 0 || nowMs - g_lastTimeSyncMs >= TIME_SYNC_INTERVAL_MS)) {

        g_lastTimeSyncMs = nowMs;

        if (mode == ConnectionMode::BLUETOOTH ||
            (mode == ConnectionMode::AUTO && btManager.isConnected())) {
            // Ask the BLE bridge for a fresh time sample.
            JsonDocument req;
            req["type"] = "get_time";
            req["pad_uuid"] = storage.getPadUUID();
            String out;
            serializeJson(req, out);
            btManager.sendJsonLine(out);
            Serial.println("[Time][BLE] Sent periodic get_time request to host");
        } else if (mode == ConnectionMode::WIFI ||
                   (mode == ConnectionMode::AUTO && WiFi.status() == WL_CONNECTED)) {
            // In WiFi mode, rely on the API/WebSocket side to push time
            // updates when it sees this hint. Here we just log; a future
            // enhancement could send an explicit HTTP/WS request.
            Serial.println("[Time][WiFi] Time sync interval reached; host should push current time over WebSocket");
        }
    }

    // Check for control panel access (hidden gesture)
    int x, y;
    static unsigned long touchStart = 0;
    static bool touching = false;
    static int lastTouchX = 0;
    static int lastTouchY = 0;
    static unsigned long lastLockScreenStateRequestMs = 0;

    if (display.getTouch(&x, &y)) {
        if (g_hostDisplayLocked) {
            if (!touching) {
                touching = true;
                touchStart = millis();
                lastTouchX = x;
                lastTouchY = y;
            }
            return;
        }

        // Check for taskbar touch first (config gear)
        if (buttonRenderer.checkTaskbarTouch(x, y)) {
            Serial.println("[Main] Config gear touched, showing PIN entry");
            // Require PIN
            String pin;
            PINResult result = pinKeypad.enterPIN(pin, "Control Panel PIN");

            if (result == PINResult::SUCCESS) {
                enterState(AppState::CONTROL_PANEL);
            } else {
                // Redraw buttons
                buttonRenderer.invalidateLayout();
                buttonRenderer.forceRefresh();
            }
            return;  // Skip rest of touch handling
        }

        if (!touching) {
            touching = true;
            touchStart = millis();
        }

        // Track last touch coordinates for tap detection on release
        lastTouchX = x;
        lastTouchY = y;

        unsigned long pressDuration = millis() - touchStart;

        // Check for long press (5 seconds) anywhere on screen for pairing reset
        if (pressDuration >= 5000) {
            // Show reset pairing confirmation
            buttonRenderer.resetLongPress();
            display.clear();
            display.setTextSize(2);
            display.setTextDatum(TC_DATUM);
            display.setTextColor(COLOR_RED, COLOR_BLACK);
            display.drawCentreString("Reset Pairing?", SCREEN_WIDTH/2, 60);
            display.setTextSize(1);
            display.setTextColor(COLOR_WHITE, COLOR_BLACK);
            display.drawCentreString("Hold to confirm (3s)", SCREEN_WIDTH/2, 100);
            display.drawCentreString("Release to cancel", SCREEN_WIDTH/2, 120);

            // Wait for user to release or hold longer
            unsigned long confirmStart = millis();
            bool confirmed = false;
            while (display.getTouch(nullptr, nullptr)) {
                if (millis() - confirmStart > 3000) {
                    confirmed = true;
                    break;
                }
                delay(50);
            }

            if (confirmed) {
                // Reset pairing
                storage.setPaired(false);
                storage.setApiUUID("");
                storage.setApiHost("");
                storage.setApiIP("");
                storage.setDeviceToken("");
                configLoaded = false;
                buttonsDirty = true;

                display.clear();
                display.setTextSize(2);
                display.setTextColor(COLOR_GREEN, COLOR_BLACK);
                display.drawCentreString("Pairing Reset!", SCREEN_WIDTH/2, 100);
                delay(2000);

                // After clearing pairing, re-run discovery to find a host
                enterState(AppState::DISCOVERY_WAITING);
                return;
            } else {
                // Cancelled, redraw buttons
                buttonRenderer.invalidateLayout();
                buttonRenderer.render();
            }
        }
        // Check for hidden menu gesture (top area long press)
        else if (controlPanel.checkHiddenMenuGesture(x, y, pressDuration)) {
            // Require PIN
            String pin;
            PINResult result = pinKeypad.enterPIN(pin, "Control Panel PIN");

            if (result == PINResult::SUCCESS) {
                enterState(AppState::CONTROL_PANEL);
            } else {
                // Redraw buttons
                buttonRenderer.invalidateLayout();
                buttonRenderer.render();
            }
        }
        // For normal button taps, we now wait until touch is released and
        // handle the press in the no-touch branch below so we only send one
        // event per tap.
    } else {
        // Touch just ended - treat as a tap if it was short and not
        // consumed by long-press gestures.
        if (touching) {
            unsigned long pressDuration = millis() - touchStart;
            if (g_hostDisplayLocked) {
                unsigned long now = millis();
                if (pressDuration < 5000 &&
                    (lastLockScreenStateRequestMs == 0 || now - lastLockScreenStateRequestMs >= 750)) {
                    lastLockScreenStateRequestMs = now;
                    requestCurrentHostSessionState();
                }
            } else if (pressDuration < 5000) {
                buttonRenderer.handleTouch(lastTouchX, lastTouchY);
            }
        }
        touching = false;
    }

    // Check for config updates via WebSocket
    // (Handled by apiClient.loop())
    if (configUpdateRequested) {
        configLoaded = false;
        buttonsDirty = true;
        configUpdateRequested = false;
        return;
    }

    // Periodic config version check. In pure Bluetooth mode we avoid calling
    // the HTTP API entirely so that no WiFi/DNS activity occurs while the pad
    // is operating over BLE only.
    static unsigned long lastCheck = 0;
    // We keep a failure counter only for logging; connection timeouts no
    // longer trigger an automatic "reset configuration" popup.
    static int connectionFailures = 0;
    if (getConnectionMode() != ConnectionMode::BLUETOOTH &&
        millis() - lastCheck > CONFIG_CHECK_INTERVAL_MS) {
        lastCheck = millis();

        uint32_t version;
        bool updateRequired;
        APIStatus status = apiClient.checkConfigVersion(version, updateRequired);

        if (status == APIStatus::OK) {
            connectionFailures = 0;  // Reset on success
            if (updateRequired) {
                // Reload config
                configLoaded = false;
                buttonsDirty = true;
            }
        } else if (status == APIStatus::AUTH_ERROR) {
            // Authentication failed - just retry, don't reset
            Serial.println("[Main] Auth error - will retry");
            delay(5000);  // Wait 5 seconds before retry
        } else {
            // Connection or network error: keep retrying indefinitely.
            connectionFailures++;
            Serial.println("[Main] Connection failure #" + String(connectionFailures));
            // No automatic reset-pairing popup here anymore; the user can
            // still access reset options via the control panel or long-press.
        }
    }

    // Keep the taskbar connection indicators (WiFi/API) in sync by redrawing
    // the top bar when connectivity actually changes, and allow a limited
    // periodic refresh while WiFi is OK but the API is disconnected so the
    // API status dot can flash yellow.
    static bool lastWifiConnected = false;
    static bool lastApiConnected = false;
    static unsigned long lastStatusRefresh = 0;

    bool wifiConnected = (WiFi.status() == WL_CONNECTED);
    bool apiConnected = apiClient.isWebSocketConnected();
    unsigned long now = millis();

    bool apiBlinking = wifiConnected && !apiConnected;

    if (wifiConnected != lastWifiConnected ||
        apiConnected != lastApiConnected ||
        (apiBlinking && (now - lastStatusRefresh > 500))) {
        lastWifiConnected = wifiConnected;
        lastApiConnected = apiConnected;
        lastStatusRefresh = now;

        // Redraw only the taskbar; buttons and page indicators remain intact.
        buttonRenderer.drawTaskbar();
    }
}

void showConnectionFailedPopup() {
    // Show popup asking to reset pairing
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLACK);
    display.drawCentreString("Connection Failed", SCREEN_WIDTH/2, 30);

    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Cannot connect to server", SCREEN_WIDTH/2, 70);
    display.drawCentreString("after 3 attempts.", SCREEN_WIDTH/2, 85);

    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString("Reset pairing?", SCREEN_WIDTH/2, 105);

    // Draw Yes button
    display.fillRoundRect(30, 130, 80, 40, 8, COLOR_RED);
    display.drawRoundRect(30, 130, 80, 40, 8, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.setTextSize(2);
    display.drawCentreString("YES", 70, 150);

    // Draw No button
    display.fillRoundRect(130, 130, 80, 40, 8, COLOR_GREEN);
    display.drawRoundRect(130, 130, 80, 40, 8, COLOR_WHITE);
    display.setTextColor(COLOR_BLACK, COLOR_GREEN);
    display.drawCentreString("NO", 170, 150);

    // Wait for user choice
    while (true) {
        int tx, ty;
        if (display.getTouch(&tx, &ty)) {
            // Check Yes button - reset pairing
            if (tx >= 30 && tx < 110 && ty >= 130 && ty < 170) {
                storage.setPaired(false);
                storage.setApiUUID("");
                storage.setApiHost("");
                storage.setApiIP("");
                storage.setDeviceToken("");
                configLoaded = false;

                display.clear();
                display.setTextSize(2);
                display.setTextColor(COLOR_GREEN, COLOR_BLACK);
                display.drawCentreString("Pairing Reset!", SCREEN_WIDTH/2, 100);
                delay(2000);

                // Go to discovery instead of restarting
                enterState(AppState::DISCOVERY_WAITING);
                return;
            }
            // Check No button - dismiss popup
            else if (tx >= 130 && tx < 210 && ty >= 130 && ty < 170) {
                // Clear background and fully redraw main UI (top bar + buttons)
                display.fillScreen(COLOR_BG_DARK);
                buttonRenderer.forceRefresh();
                return;
            }
        }
        delay(50);
    }
}

void handleControlPanel() {
    ControlPanelAction action = controlPanel.show();

    // Force button refresh when returning to main screen
    buttonRenderer.invalidateLayout();
    buttonRenderer.forceRefresh();

    // Return to normal operation or handle state changes
    switch (action) {
        case ControlPanelAction::WIFI_SETUP:
            enterState(AppState::WIFI_SETUP);
            break;
        case ControlPanelAction::PAIRING_SETUP:
            // Rediscover host: go back to discovery scanning
            enterState(AppState::DISCOVERY_WAITING);
            break;
        case ControlPanelAction::RESET_PAIRING:
        case ControlPanelAction::RESET_WIFI:
        case ControlPanelAction::FACTORY_RESET:
        case ControlPanelAction::NEW_PROFILE:
            // State handled by control panel, return to boot
            enterState(AppState::BOOT);
            break;
        default:
            if (storage.isPaired()) {
                enterState(AppState::NORMAL_OPERATION);
            } else {
                enterState(AppState::DISCOVERY_WAITING);
            }
            break;
    }
}

void handleError() {
    // Error state - wait for touch to retry
    int x, y;
    if (display.getTouch(&x, &y)) {
        delay(500);
        enterState(AppState::BOOT);
    }
}

bool loadConfigFromAPI() {
    Serial.println("[loadConfig] Starting...");

    extern DisplayManager display;
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_CYAN, COLOR_BLACK);
    display.drawCentreString("Connecting to server...", SCREEN_WIDTH/2, 40);
    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Please wait while buttons load", SCREEN_WIDTH/2, 80);

    // Initialize API client
    apiClient.begin();

    // Connect WebSocket
    Serial.println("[loadConfig] Connecting WebSocket...");
    apiClient.connectWebSocket();
    apiClient.onConfigUpdate([](const String&, JsonDocument&) {
        extern bool configLoaded;
        extern bool buttonsDirty;
        configLoaded = false;
        buttonsDirty = true;
    });

    // Start log session once WebSocket is up so the API can group logs for
    // this boot.
    apiClient.startLogSession(g_logSessionUUID, "BOOT", String(FW_VERSION));

    // Get config
    Serial.println("[loadConfig] Getting config from API...");
    APIStatus status = apiClient.getConfig(currentConfig);
    Serial.println("[loadConfig] getConfig status: " + String((int)status));

    if (status == APIStatus::OK) {
        Serial.println("[loadConfig] Config received, buttons: " + String(currentConfig.buttonCount));

        // Load into button renderer and force refresh
        buttonRenderer.loadConfig(currentConfig);
        buttonRenderer.forceRefresh();
        storage.setConfigVersion(currentConfig.configVersion);

        // Confirm config applied
        apiClient.confirmConfigApplied(currentConfig.configVersion);

        configLoaded = true;
        sendPadStatusSnapshot();
        Serial.println("[loadConfig] Success!");
        return true;
    }

    // Check for authentication error - just retry, don't reset
    if (status == APIStatus::AUTH_ERROR) {
        Serial.println("[loadConfig] Auth error - will retry");
        delay(5000);
        return false;
    }

    Serial.println("[loadConfig] Failed to load config");
    return false;
}

bool loadConfigFromBLE() {
    Serial.print("[");
    Serial.print(millis());
    Serial.print(" ms] ");
    Serial.println("[loadConfigBLE] Starting...");

    const unsigned long CONNECT_TIMEOUT_MS = 10000;
    unsigned long start = millis();

    // Show a full-screen status view while we wait for the BLE bridge to
    // connect and provide configuration. If there is no active Bluetooth
    // pairing PIN yet, automatically start a pairing session so we can show
    // the PIN here.
    display.clear();

    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_CYAN, COLOR_BLACK);
    display.drawCentreString("Waiting for host...", SCREEN_WIDTH/2, SCREEN_HEIGHT/2 - 20);

    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Ensure the Bluetooth bridge is running", SCREEN_WIDTH/2, SCREEN_HEIGHT/2 + 5);

    // Ensure we have a pairing PIN; if none exists yet, start a new pairing
    // session so the host can enter this code during Bluetooth pairing.
    extern BluetoothManager btManager;
    String currentPin = btManager.getCurrentPin();
    if (currentPin.length() == 0) {
        currentPin = btManager.startPairingSession();
    }
    if (currentPin.length() > 0) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        String line = String("Pairing code: ") + currentPin;
        display.drawCentreString(line, SCREEN_WIDTH/2, SCREEN_HEIGHT/2 + 30);
    }


    // Wait briefly for an existing BLE connection (from the host bridge).
    while (!btManager.isConnected() && millis() - start < CONNECT_TIMEOUT_MS) {
        btManager.loop();
        delay(10);
    }

    if (!btManager.isConnected()) {
        Serial.print("[");
        Serial.print(millis());
        Serial.print(" ms] ");
        Serial.println("[loadConfigBLE] No BLE connection available");
        return false;
    }

    // At this point we have an active BLE connection to a host/bridge. Update
    // the on-screen status so the pairing code is no longer shown and users
    // instead see that we are connected and loading the button configuration.
    display.clear();

    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
    display.drawCentreString("Bluetooth connected", SCREEN_WIDTH/2, SCREEN_HEIGHT/2 - 10);

    display.setTextColor(COLOR_CYAN, COLOR_BLACK);
    display.drawCentreString("Loading buttons...", SCREEN_WIDTH/2, SCREEN_HEIGHT/2 + 20);

    // Send a get_config request to the host over BLE.
    JsonDocument req;
    req["type"] = "get_config";
    req["pad_uuid"] = storage.getPadUUID();

    String out;
    serializeJson(req, out);

    Serial.print("[");
    Serial.print(millis());
    Serial.print(" ms] ");
    Serial.println("[loadConfigBLE] Sending get_config over BLE: " + out);
    if (!btManager.sendJsonLine(out)) {
        Serial.print("[");
        Serial.print(millis());
        Serial.print(" ms] ");
        Serial.println("[loadConfigBLE] Failed to send get_config over BLE");
        return false;
    }

    // Wait for a config reply from the host bridge. The BLE bridge currently
    // sends the JSON in many small (20-byte) chunks with write-with-response,
    // which can take several seconds on some adapters. Use a moderate total
    // timeout and a shorter idle timeout so we fail fast and retry instead of
    // sitting for a full minute when the host is not responding.
    const unsigned long REPLY_TIMEOUT_MS = 40000;   // total wait budget
    const unsigned long IDLE_RX_TIMEOUT_MS = 15000;  // idle before giving up and retrying
    unsigned long waitStart = millis();
    unsigned long initialLastRx = btManager.getLastRxActivityMs();
    std::vector<String> lines;

    while (millis() - waitStart < REPLY_TIMEOUT_MS) {
        btManager.loop();
        btManager.drainPendingLines(lines);

        unsigned long nowMs = millis();
        unsigned long lastRx = btManager.getLastRxActivityMs();
        bool hasRxSinceStart = (lastRx != 0 && lastRx != initialLastRx);

        if (!hasRxSinceStart && nowMs - waitStart >= IDLE_RX_TIMEOUT_MS) {
            Serial.print("[");
            Serial.print(nowMs);
            Serial.print(" ms] ");
            Serial.println("[loadConfigBLE] Timed out waiting for config over BLE (no RX activity)");
            return false;
        }

        for (const String& line : lines) {
            Serial.print("[");
            Serial.print(millis());
            Serial.print(" ms] ");
            Serial.println("[loadConfigBLE] RX: " + line);

            JsonDocument doc;
            DeserializationError err = deserializeJson(doc, line);
            if (err) {
                Serial.print("[");
                Serial.print(millis());
                Serial.print(" ms] ");
                Serial.println("[loadConfigBLE] JSON parse error: " + String(err.c_str()));
                continue;
            }

            String type = doc["type"].as<String>();
            if (type == "hello") {
                continue;
            }
            if (type == "time") {
                long epoch = doc["epoch"] | 0;
                if (epoch > 0) {
                    struct timeval tv;
                    tv.tv_sec = epoch;
                    tv.tv_usec = 0;
                    settimeofday(&tv, nullptr);
                    Serial.print("[Time][BLE] Time set from host during loadConfigBLE, epoch=");
                    Serial.println(epoch);
                }
                continue;
            }
            if (type != "config") {
                continue;
            }

            JsonObject cfg = doc["config"].as<JsonObject>();
            if (cfg.isNull()) {
                Serial.println("[loadConfigBLE] config field missing in reply");
                continue;
            }

            // Parse PadConfig from the config object (mirrors APIClient::getConfig).
            currentConfig.padId = cfg["pad_id"].as<String>();
            currentConfig.name = cfg["name"].as<String>();
            currentConfig.mode = cfg["pad_mode"].as<String>();
            currentConfig.buttonCount = cfg["button_count"];  // per page
            currentConfig.pageCount = cfg["page_count"] | 1;
            currentConfig.configVersion = cfg["config_version"];
            currentConfig.columns = cfg["layout"]["columns"];
            currentConfig.rows = cfg["layout"]["rows"];

            // Time configuration for top bar (formatting only; the ESP32
            // clock itself is kept in sync with the host's local time, so we
            // ignore any timezone offsets here).
            JsonObject timeCfg = cfg["time"].as<JsonObject>();
            if (!timeCfg.isNull()) {
                currentConfig.use24h = timeCfg["use_24h"] | false;
                currentConfig.showAmPm = timeCfg["show_am_pm"] | true;
            } else {
                currentConfig.use24h = false;
                currentConfig.showAmPm = true;
            }

            currentConfig.buttons.clear();
            JsonArray buttons = cfg["buttons"];
            for (JsonObject btn : buttons) {
                ButtonConfig bc;
                bc.page = btn["page"] | 1;
                bc.slot = btn["slot"];
                bc.x = btn["x"];
                bc.y = btn["y"];
                bc.w = btn["w"];
                bc.h = btn["h"];
                bc.label = btn["label"].as<String>();
                bc.iconId = btn["icon_id"].as<String>();
                bc.actionId = btn["action_id"].as<String>();
                bc.bgColorHex = btn["bg_color"].as<String>();
                bc.iconColorHex = btn["icon_color"].as<String>();
                bc.textColorHex = btn["text_color"].as<String>();
                bc.showText = btn["show_text"] | true;
                bc.applicationId = btn["application_id"] | 0;
                bc.hasApplicationIcon = btn["has_application_icon"] | false;
                bc.applicationIconVersion = btn["application_icon_version"].as<String>();
                currentConfig.buttons.push_back(bc);
            }

            // Load into button renderer and force refresh.
            buttonRenderer.loadConfig(currentConfig);
            buttonRenderer.forceRefresh();
            storage.setConfigVersion(currentConfig.configVersion);

            configLoaded = true;
            sendPadStatusSnapshot();
            Serial.print("[");
            Serial.print(millis());
            Serial.print(" ms] ");
            Serial.println("[loadConfigBLE] Success!");
            return true;
        }

        lines.clear();
        delay(10);
    }

    Serial.print("[");
    Serial.print(millis());
    Serial.print(" ms] ");
    Serial.println("[loadConfigBLE] Timed out waiting for config over BLE");
    return false;
}

void requestCurrentHostSessionState() {
    ConnectionMode mode = getConnectionMode();

    if (mode == ConnectionMode::BLUETOOTH ||
        (mode == ConnectionMode::AUTO && btManager.isConnected())) {
        JsonDocument req;
        req["type"] = "get_host_session_state";
        req["pad_uuid"] = storage.getPadUUID();
        String out;
        serializeJson(req, out);
        if (btManager.sendJsonLine(out)) {
            Serial.println("[POWER] Requested current host session state over BLE");
        } else {
            Serial.println("[POWER] Failed to request current host session state over BLE");
        }
        return;
    }

    if (mode == ConnectionMode::WIFI ||
        (mode == ConnectionMode::AUTO && WiFi.status() == WL_CONNECTED)) {
        bool locked = true;
        APIStatus status = apiClient.getHostSessionState(locked);
        if (status == APIStatus::OK) {
            if (!locked) {
                g_hostDisplayLocked = false;
                buttonsDirty = true;
                Serial.println("[POWER] Host already unlocked; clearing ESP32 lock screen");
            } else {
                Serial.println("[POWER] Host still locked; keeping ESP32 lock screen");
            }
        } else {
            Serial.println("[POWER] Failed to query current host session state over HTTP");
        }
    }
}

void showError(const String& message) {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLACK);
    display.drawCentreString("ERROR", SCREEN_WIDTH/2, 60);
    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString(message, SCREEN_WIDTH/2, 100);
    display.drawCentreString("Touch to restart", SCREEN_WIDTH/2, 160);
    enterState(AppState::ERROR);
}

void handleLastServerConnect() {
    static bool firstRun = true;
    static unsigned long startTime = 0;
    static unsigned long lastAttempt = 0;

    if (firstRun) {
        firstRun = false;
        startTime = millis();
        lastAttempt = 0;

        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_CYAN, COLOR_BLACK);
        display.drawCentreString("Connecting to server...", SCREEN_WIDTH/2, 40);

        String lastApiIp = storage.getApiIP();
        display.setTextSize(1);
        display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
        display.drawCentreString("Last API IP: " + lastApiIp, SCREEN_WIDTH/2, 80);

        Serial.println("[LastServer] Trying stored API IP " + lastApiIp +
                       " for up to 5 minutes before scanning network");
    }

    // If WiFi drops while we're here, go back to BOOT to re-evaluate
    if (WiFi.status() != WL_CONNECTED) {
        Serial.println("[LastServer] WiFi lost while trying last server - returning to BOOT");
        firstRun = true;
        enterState(AppState::BOOT);
        return;
    }

    unsigned long now = millis();

    // Give up after 5 minutes and fall back to discovery scanning
    if (now - startTime > 300000UL) {  // 5 minutes
        Serial.println("[LastServer] Timed out, starting discovery scan instead");

        // Bump diagnostic counter so we can see how often this happens
        uint32_t fails = storage.getLastIpFailureCount();
        storage.setLastIpFailureCount(fails + 1);

        // Briefly inform the user on-screen that we're switching to a full scan
        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
        display.drawCentreString("Server not found", SCREEN_WIDTH/2, 60);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Scanning network for host...", SCREEN_WIDTH/2, 100);
        delay(2000);

        firstRun = true;
        discovery.begin();
        enterState(AppState::DISCOVERY_WAITING);
        return;
    }

    // Throttle connection attempts (e.g. every 5 seconds)
    if (now - lastAttempt < 5000UL) {
        return;
    }
    lastAttempt = now;

    Serial.println("[LastServer] Attempting to load config from stored API IP...");

    // Clear any previous config-loaded flag so loadConfigFromAPI will fetch again
    configLoaded = false;

    if (loadConfigFromAPI()) {
        Serial.println("[LastServer] Successfully connected to stored API IP");
        firstRun = true;
        // We already loaded config and initialized renderer; proceed to normal operation
        enterState(AppState::NORMAL_OPERATION);
    } else {
        Serial.println("[LastServer] Config load failed, will retry while within 5-minute window");
    }
}
