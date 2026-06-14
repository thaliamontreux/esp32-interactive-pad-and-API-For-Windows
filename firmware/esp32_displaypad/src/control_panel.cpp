#include "control_panel.h"
#include "storage.h"
#include "wifi_manager.h"
#include "api_client.h"
#include "pin_keypad.h"
#include "text_keyboard.h"

ControlPanel controlPanel;

const char* ControlPanel::menuLabels[MENU_ITEMS] = {
    "WiFi Setup",
    "Rediscover Host",
    "Device Diagnostics",
    "Host Diagnostics",
    "Config Refresh",
    "Reconnect API",
    "Reset Pairing Only",
    "Reset WiFi Only",
    "Factory Reset",
    "New Pad Profile",
    "Exit"
};

const ControlPanelAction ControlPanel::menuActions[MENU_ITEMS] = {
    ControlPanelAction::WIFI_SETUP,
    ControlPanelAction::PAIRING_SETUP,
    ControlPanelAction::DEVICE_DIAGNOSTICS,
    ControlPanelAction::HOST_DIAGNOSTICS,
    ControlPanelAction::CONFIG_REFRESH,
    ControlPanelAction::RECONNECT_API,
    ControlPanelAction::RESET_PAIRING,
    ControlPanelAction::RESET_WIFI,
    ControlPanelAction::FACTORY_RESET,
    ControlPanelAction::NEW_PROFILE,
    ControlPanelAction::EXIT
};

ControlPanel::ControlPanel() : selectedIndex(0), active(false), startupWindowStart(0) {}

bool ControlPanel::begin() {
    return true;
}

bool ControlPanel::showStartupWindow() {
    startupWindowStart = millis();

    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("DisplayPad", SCREEN_WIDTH/2, 40);

    display.setTextSize(1);
    display.drawCentreString("Press anywhere for Control Panel", SCREEN_WIDTH/2, 100);

    // Show countdown
    display.setTextSize(2);
    display.setTextColor(COLOR_ACCENT, COLOR_BLACK);

    unsigned long startTime = millis();
    Serial.println("[ControlPanel] Startup window waiting for touch...");
    while (millis() - startTime < STARTUP_CONTROL_PANEL_WINDOW_MS) {
        // Check for touch
        int x, y;
        if (display.getTouch(&x, &y)) {
            Serial.println("[ControlPanel] Touch detected at x=" + String(x) + " y=" + String(y));

            // Enter control panel
            delay(300);  // Debounce

            // Require PIN
            String pin;
            Serial.println("[ControlPanel] Showing PIN keypad...");
            PINResult result = pinKeypad.enterPIN(pin, "Control Panel PIN");
            Serial.println("[ControlPanel] PIN result: " + String((int)result));

            if (result == PINResult::SUCCESS) {
                Serial.println("[ControlPanel] PIN success, showing menu...");
                ControlPanelAction action = show();
                return action != ControlPanelAction::NONE;
            }
            Serial.println("[ControlPanel] PIN failed or cancelled");
            return false;
        }

        // Update countdown
        int remaining = (STARTUP_CONTROL_PANEL_WINDOW_MS - (millis() - startTime)) / 1000;
        String countStr = String(remaining) + "s";
        display.fillRect(SCREEN_WIDTH/2 - 30, 150, 60, 30, COLOR_BLACK);
        display.drawCentreString(countStr, SCREEN_WIDTH/2, 160);

        delay(100);
    }

    return false;  // Window expired, no action
}

ControlPanelAction ControlPanel::show() {
    Serial.println("[ControlPanel] show() called");
    selectedIndex = 0;
    active = true;

    Serial.println("[ControlPanel] Drawing main menu...");
    drawMainMenu();
    Serial.println("[ControlPanel] Menu drawn, entering touch loop...");

    while (active) {
        int x, y;
        if (display.getTouch(&x, &y)) {
            delay(200);  // Debounce

            // Check for X (close) button touch at top right
            if (x > SCREEN_WIDTH - 30 && y < 30) {
                Serial.println("[ControlPanel] X button touched, closing");
                active = false;
                return ControlPanelAction::NONE;
            }

            // Check for swipe down from top (hidden menu gesture)
            if (y < 30 && x > SCREEN_WIDTH - 50) {
                // Long press area
                unsigned long pressStart = millis();
                while (display.getTouch(&x, &y)) {
                    if (millis() - pressStart > 1000) {
                        // Long press detected
                        break;
                    }
                    delay(10);
                }
            }

            int item = getMenuItemAt(x, y);
            if (item >= 0) {
                selectedIndex = item;
                drawMainMenu();
                delay(100);

                ControlPanelAction action = menuActions[selectedIndex];
                executeAction(action);

                if (action == ControlPanelAction::EXIT) {
                    active = false;
                    return ControlPanelAction::NONE;
                }

                // Redraw menu after action
                if (active) {
                    drawMainMenu();
                }
            }
        }

        delay(10);
    }

    return ControlPanelAction::NONE;
}

void ControlPanel::drawMainMenu() {
    Serial.println("[ControlPanel] drawMainMenu() starting...");
    display.clear();

    // Title bar
    display.fillRect(0, 0, SCREEN_WIDTH, 30, COLOR_BLUE);
    display.setTextSize(2);
    display.setTextDatum(MC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLUE);
    display.drawCentreString("Control Panel", SCREEN_WIDTH/2, 15);

    // Close button (X) at top right
    display.setTextDatum(TR_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLUE);
    display.drawString("X", SCREEN_WIDTH - 8, 8);
    display.setTextDatum(MC_DATUM);  // Reset datum

    // Menu items
    int startY = 40;
    int itemHeight = 24;

    for (int i = 0; i < MENU_ITEMS; i++) {
        int y = startY + i * itemHeight;
        drawMenuItem(y, menuLabels[i], i == selectedIndex);
    }
    Serial.println("[ControlPanel] drawMainMenu() complete");
}

void ControlPanel::drawMenuItem(int y, const String& text, bool selected) {
    uint16_t bgColor = selected ? COLOR_ACCENT : COLOR_BLACK;
    uint16_t textColor = selected ? COLOR_BLACK : COLOR_WHITE;

    display.fillRect(5, y, SCREEN_WIDTH - 10, 22, bgColor);
    display.drawRect(5, y, SCREEN_WIDTH - 10, 22, COLOR_GRAY);

    display.setTextSize(1);
    display.setTextDatum(ML_DATUM);
    display.setTextColor(textColor, bgColor);
    display.drawString(text, 15, y + 11);
}

int ControlPanel::getMenuItemAt(int x, int y) {
    int startY = 40;
    int itemHeight = 24;

    for (int i = 0; i < MENU_ITEMS; i++) {
        int itemY = startY + i * itemHeight;
        if (y >= itemY && y < itemY + 22 && x >= 5 && x < SCREEN_WIDTH - 5) {
            return i;
        }
    }
    return -1;
}

void ControlPanel::executeAction(ControlPanelAction action) {
    switch (action) {
        case ControlPanelAction::WIFI_SETUP:
            showWiFiSetup();
            break;
        case ControlPanelAction::PAIRING_SETUP:
            // Restart discovery scanning so the pad can find a new host
            Serial.println("[ControlPanel] Rediscover host requested - restarting discovery");
            storage.setPaired(false);
            storage.setApiUUID("");
            storage.setApiHost("");
            storage.setApiIP("");
            storage.setDeviceToken("");
            // WiFi remains configured; main loop will enter DISCOVERY_WAITING on next state change
            break;
        case ControlPanelAction::DEVICE_DIAGNOSTICS:
            showDeviceDiagnostics();
            break;
        case ControlPanelAction::HOST_DIAGNOSTICS:
            showHostDiagnostics();
            break;
        case ControlPanelAction::CONFIG_REFRESH:
            // Trigger config refresh
            break;
        case ControlPanelAction::RECONNECT_API:
            wifiManager.reconnect();
            break;
        case ControlPanelAction::RESET_PAIRING:
            if (confirmReset("Reset Pairing?", "Clear all pairing data?")) {
                doResetPairing();
            }
            break;
        case ControlPanelAction::RESET_WIFI:
            if (confirmReset("Reset WiFi?", "Clear WiFi credentials?")) {
                doResetWiFi();
            }
            break;
        case ControlPanelAction::FACTORY_RESET:
            if (confirmReset("FACTORY RESET?", "Erase ALL data?")) {
                doFactoryReset();
            }
            break;
        case ControlPanelAction::NEW_PROFILE:
            if (confirmReset("New Profile?", "Generate new pad identity?")) {
                doGenerateNewProfile();
            }
            break;
        default:
            break;
    }
}

void ControlPanel::showWiFiSetup() {
    // Scan for WiFi networks
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("WiFi Setup", SCREEN_WIDTH/2, 20);

    display.setTextSize(1);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString("Scanning...", SCREEN_WIDTH/2, 60);

    Serial.println("[WiFi] Scanning for networks...");
    int numNetworks = WiFi.scanNetworks();
    Serial.println("[WiFi] Found " + String(numNetworks) + " networks");

    if (numNetworks == 0) {
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        display.drawCentreString("No networks found", SCREEN_WIDTH/2, 80);
        display.drawCentreString("Touch to continue", SCREEN_WIDTH/2, 100);
        while (!display.getTouch(nullptr, nullptr)) { delay(10); }
        delay(300);
        return;
    }

    // Show network list (scrollable, max 5 visible at a time)
    int selectedIndex = 0;
    int topIndex = 0;
    const int visibleNetworks = 5;
    bool selecting = true;

    while (selecting) {
        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Select WiFi", SCREEN_WIDTH/2, 10);

        // Draw networks
        display.setTextSize(1);
        for (int i = 0; i < visibleNetworks && (topIndex + i) < numNetworks; i++) {
            int idx = topIndex + i;
            int y = 35 + i * 30;

            // Highlight selected
            if (idx == selectedIndex) {
                display.fillRect(5, y, SCREEN_WIDTH - 10, 28, COLOR_ACCENT);
                display.setTextColor(COLOR_BLACK, COLOR_ACCENT);
            } else {
                display.fillRect(5, y, SCREEN_WIDTH - 10, 28, COLOR_DARK_GRAY);
                display.setTextColor(COLOR_WHITE, COLOR_DARK_GRAY);
            }
            display.drawRect(5, y, SCREEN_WIDTH - 10, 28, COLOR_GRAY);

            // SSID
            String ssid = WiFi.SSID(idx);
            if (ssid.length() > 20) ssid = ssid.substring(0, 17) + "...";
            display.setTextDatum(ML_DATUM);
            display.drawString(ssid, 10, y + 14);

            // Signal strength
            int rssi = WiFi.RSSI(idx);
            display.setTextDatum(MR_DATUM);
            String signal = String(rssi) + " dBm";
            display.drawString(signal, SCREEN_WIDTH - 35, y + 14);

            // Lock icon for secured networks
            if (WiFi.encryptionType(idx) != WIFI_AUTH_OPEN) {
                display.fillCircle(SCREEN_WIDTH - 15, y + 14, 4, COLOR_YELLOW);
            }
        }

        // Instructions
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Tap network to select", SCREEN_WIDTH/2, 185);

        // Wait for touch
        int tx, ty;
        while (!display.getTouch(&tx, &ty)) { delay(10); }

        // Check for scroll (top/bottom area)
        if (ty < 35) {
            // Scroll up
            if (selectedIndex > 0) {
                selectedIndex--;
                if (selectedIndex < topIndex) topIndex = selectedIndex;
            }
        } else if (ty > 175) {
            // Scroll down
            if (selectedIndex < numNetworks - 1) {
                selectedIndex++;
                if (selectedIndex >= topIndex + visibleNetworks) topIndex++;
            }
        } else {
            // Check which network was tapped
            int tappedIndex = (ty - 35) / 30 + topIndex;
            if (tappedIndex >= 0 && tappedIndex < numNetworks) {
                selectedIndex = tappedIndex;
                selecting = false;
            }
        }

        delay(200);
    }

    // Get selected network
    String selectedSSID = WiFi.SSID(selectedIndex);
    bool isEncrypted = WiFi.encryptionType(selectedIndex) != WIFI_AUTH_OPEN;

    Serial.println("[WiFi] Selected: " + selectedSSID);

    // Get password if encrypted
    String password = "";
    if (isEncrypted) {
        bool gotPassword = textKeyboard.getInput(password, "Enter password for:\n" + selectedSSID);
        if (!gotPassword) {
            Serial.println("[WiFi] Password entry cancelled");
            WiFi.scanDelete();
            return;
        }
    }

    // Connect to WiFi
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Connecting...", SCREEN_WIDTH/2, 80);

    display.setTextSize(1);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString(selectedSSID, SCREEN_WIDTH/2, 120);

    Serial.println("[WiFi] Connecting to " + selectedSSID + "...");

    WiFi.mode(WIFI_STA);
    WiFi.begin(selectedSSID.c_str(), password.c_str());

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        display.fillRect(20, 150, SCREEN_WIDTH - 40, 10, COLOR_BLACK);
        display.fillRect(20, 150, (attempts * (SCREEN_WIDTH - 40)) / 30, 10, COLOR_GREEN);
        attempts++;
    }

    WiFi.scanDelete();

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("[WiFi] Connected! IP: " + WiFi.localIP().toString());

        // Save credentials
        storage.setWiFiSSID(selectedSSID);
        storage.setWiFiPass(password);

        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawCentreString("Connected!", SCREEN_WIDTH/2, 80);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString(WiFi.localIP().toString(), SCREEN_WIDTH/2, 120);
    } else {
        Serial.println("[WiFi] Connection failed");

        display.clear();
        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        display.drawCentreString("Failed!", SCREEN_WIDTH/2, 80);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Check password and try again", SCREEN_WIDTH/2, 120);
    }

    display.drawCentreString("Touch to continue", SCREEN_WIDTH/2, 160);
    while (!display.getTouch(nullptr, nullptr)) { delay(10); }
    delay(300);
}

void ControlPanel::showPairingSetup() {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Pairing Setup", SCREEN_WIDTH/2, 20);

    // Show current pairing status
    display.setTextSize(1);

    if (storage.isPaired()) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawCentreString("Paired", SCREEN_WIDTH/2, 60);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("API: " + storage.getApiHost(), SCREEN_WIDTH/2, 80);
    } else {
        display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
        display.drawCentreString("Not Paired", SCREEN_WIDTH/2, 60);
    }

    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Pad UUID:", SCREEN_WIDTH/2, 110);
    display.drawCentreString(storage.getPadUUID(), SCREEN_WIDTH/2, 130);

    // Wait for touch
    delay(2000);
    while (!display.getTouch(nullptr, nullptr)) {
        delay(10);
    }
}

void ControlPanel::showDeviceDiagnostics() {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Device Status", SCREEN_WIDTH/2, 20);

    display.setTextSize(1);
    int y = 60;

    // WiFi status
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawString("WiFi: ", 20, y);
    if (wifiManager.isConnected()) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawString("Connected (" + String(wifiManager.getRSSI()) + " dBm)", 70, y);
    } else {
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        display.drawString("Disconnected", 70, y);
    }
    y += 25;

    // IP address
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawString("IP: " + wifiManager.getIP(), 20, y);
    y += 25;

    // API status
    display.drawString("API: ", 20, y);
    if (apiClient.isWebSocketConnected()) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawString("Connected (WS)", 70, y);
    } else {
        display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
        display.drawString("HTTP only", 70, y);
    }
    y += 25;

    // Pad UUID
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawString("UUID:", 20, y);
    y += 15;
    String uuid = storage.getPadUUID();
    if (uuid.length() > 25) {
        uuid = uuid.substring(0, 22) + "...";
    }
    display.drawString(uuid, 20, y);

    // Wait for touch
    delay(2000);
    while (!display.getTouch(nullptr, nullptr)) {
        delay(10);
    }
}

void ControlPanel::showHostDiagnostics() {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Host Status", SCREEN_WIDTH/2, 20);

    display.setTextSize(1);

    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawString("API Host: " + storage.getApiHost(), 20, 60);
    display.drawString("API IP: " + storage.getApiIP(), 20, 85);
    display.drawString("API Port: " + String(storage.getApiPort()), 20, 110);
    display.drawString("Config Ver: " + String(storage.getConfigVersion()), 20, 135);

    // Wait for touch
    delay(2000);
    while (!display.getTouch(nullptr, nullptr)) {
        delay(10);
    }
}

bool ControlPanel::confirmReset(const String& title, const String& message) {
    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLACK);
    display.drawCentreString(title, SCREEN_WIDTH/2, 40);

    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString(message, SCREEN_WIDTH/2, 100);

    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString("Touch to confirm", SCREEN_WIDTH/2, 160);
    display.drawCentreString("or wait 3s to cancel", SCREEN_WIDTH/2, 180);

    // Wait for touch or timeout
    unsigned long start = millis();
    while (millis() - start < 3000) {
        if (display.getTouch(nullptr, nullptr)) {
            return true;
        }
        delay(10);
    }

    return false;
}

void ControlPanel::doResetPairing() {
    storage.setPaired(false);
    storage.setApiUUID("");
    storage.setApiHost("");
    storage.setApiIP("");
    storage.setDeviceToken("");
    storage.setConfigVersion(0);

    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
    display.drawCentreString("Pairing Reset", SCREEN_WIDTH/2, 100);
    delay(2000);
}

void ControlPanel::doResetWiFi() {
    storage.setWiFiSSID("");
    storage.setWiFiPass("");
    wifiManager.disconnect();

    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
    display.drawCentreString("WiFi Reset", SCREEN_WIDTH/2, 100);
    delay(2000);
}

void ControlPanel::doFactoryReset() {
    storage.factoryReset();
    wifiManager.disconnect();

    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BLACK);
    display.drawCentreString("Factory Reset", SCREEN_WIDTH/2, 80);
    display.drawCentreString("Complete", SCREEN_WIDTH/2, 110);
    display.drawCentreString("Rebooting...", SCREEN_WIDTH/2, 150);
    delay(3000);
    ESP.restart();
}

void ControlPanel::doGenerateNewProfile() {
    storage.generateNewProfile();

    display.clear();
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
    display.drawCentreString("New Profile", SCREEN_WIDTH/2, 80);
    display.setTextSize(1);
    display.drawCentreString(storage.getPadUUID(), SCREEN_WIDTH/2, 120);
    delay(3000);
}

bool ControlPanel::checkHiddenMenuGesture(int x, int y, unsigned long pressDuration) {
    // Check for swipe down from top (y < 30)
    // or long press on top bar
    if (y < 30 && pressDuration > 1000) {
        return true;
    }
    return false;
}
