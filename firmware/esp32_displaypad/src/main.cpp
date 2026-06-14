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
#include "config.h"
#include "storage.h"
#include "display.h"
#include "wifi_manager.h"
#include "pin_keypad.h"
#include "text_keyboard.h"
#include "ip_keyboard.h"
#include "api_client.h"
#include "button_renderer.h"
#include "control_panel.h"
#include "discovery_beacon.h"
#include "icon_cache.h"

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
void pairingScreen();
void pairingScreenLegacy();
void showError(const String& message);
void showConnectionFailedPopup();
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

// Simple helper for mirroring important log lines both to the serial console
// and to the DisplayPad API (when connected). This avoids spamming the
// network with every low-level debug print while still capturing the
// high-level lifecycle events needed for remote diagnostics.
#define DP_LOG(msg)                          \
    do {                                     \
        Serial.println(msg);                 \
        apiClient.sendLogLine(g_logSessionUUID, g_logSeq++, msg); \
    } while (0)

void setup() {
    Serial.begin(115200);
    delay(1000);
    DP_LOG("\n=== DisplayPad ESP32 Starting ===");

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

    // Initialize per-boot log session. We will notify the API about this
    // session once the WebSocket connection is established in
    // loadConfigFromAPI().
    g_logSessionUUID = generateLogSessionUUID();
    g_logSeq = 0;

    // Start in boot state
    enterState(AppState::BOOT);
}

void loop() {
    // Update WiFi manager
    wifiManager.loop();

    // Update API client WebSocket
    apiClient.loop();

    // Handle button press feedback timeout
    buttonRenderer.clearFeedback();

    // Update discovery beacon
    discovery.loop();

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
    // Check if WiFi is configured
    String ssid = storage.getWiFiSSID();

    if (ssid.length() == 0) {
        // No WiFi config - show startup window then WiFi setup
        enterState(AppState::STARTUP_WINDOW);
    } else {
        // Try to connect to saved WiFi
        DP_LOG("Connecting to saved WiFi: " + ssid);
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
        // Window expired, always go to control panel for configuration
        enterState(AppState::CONTROL_PANEL);
    }
}

void handleWiFiSetup() {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("WiFi Setup", SCREEN_WIDTH/2, 40);

    display.setTextSize(1);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString("Connect to 'DisplayPad-Setup'", SCREEN_WIDTH/2, 100);
    display.drawCentreString("and open 192.168.4.1", SCREEN_WIDTH/2, 120);

    // Start AP mode
    wifiManager.startAP();

    // Wait for configuration
    unsigned long startTime = millis();
    while (!wifiManager.isConnected()) {
        wifiManager.handleAPClient();

        // Check for timeout or touch to cancel
        if (millis() - startTime > 300000) {  // 5 minute timeout
            wifiManager.stopAP();
            enterState(AppState::ERROR);
            return;
        }

        delay(10);
    }

    // WiFi connected
    wifiManager.stopAP();

    // Save credentials and proceed
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
    // Load config if not loaded
    if (!configLoaded) {
        Serial.println("[Main] Loading config from API...");
        if (!loadConfigFromAPI()) {
            // Config load failed, go to error state
            Serial.println("[Main] Config load failed, going to ERROR");
            enterState(AppState::ERROR);
            return;
        }
        Serial.println("[Main] Config loaded, buttons: " + String(buttonRenderer.getButtonCount()));
        // After a (re)load, force a fresh render once
        buttonsDirty = true;
    }

    // Render buttons only when something changed. Use a full forceRefresh so
    // that when buttons are removed (e.g., Task Keypad apps stop running),
    // their previous drawings are cleared from the screen.
    if (buttonsDirty) {
        Serial.println("[Main] Rendering buttons (dirty=true)...");
        buttonRenderer.forceRefresh();
        buttonsDirty = false;
    }

    // Check for control panel access (hidden gesture)
    int x, y;
    static unsigned long touchStart = 0;
    static bool touching = false;
    static int lastTouchX = 0;
    static int lastTouchY = 0;

    if (display.getTouch(&x, &y)) {
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
            if (pressDuration < 5000) {
                buttonRenderer.handleTouch(lastTouchX, lastTouchY);
            }
        }
        touching = false;
    }

    // Check for config updates via WebSocket
    // (Handled by apiClient.loop())

    // Periodic config version check
    static unsigned long lastCheck = 0;
    static int connectionFailures = 0;
    if (millis() - lastCheck > CONFIG_CHECK_INTERVAL_MS) {
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
            connectionFailures++;
            Serial.println("[Main] Connection failure #" + String(connectionFailures));

            // After 3 failures, show reset pairing popup
            if (connectionFailures >= 3) {
                connectionFailures = 0;  // Reset counter
                showConnectionFailedPopup();
            }
        }
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

    // Initialize API client
    apiClient.begin();

    // Connect WebSocket
    Serial.println("[loadConfig] Connecting WebSocket...");
    apiClient.connectWebSocket();

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
