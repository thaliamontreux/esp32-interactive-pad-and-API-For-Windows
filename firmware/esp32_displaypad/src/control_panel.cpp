#include "control_panel.h"
#include "storage.h"
#include "wifi_manager.h"
#include "api_client.h"
#include "pin_keypad.h"
#include "text_keyboard.h"
#include "bluetooth_manager.h"

ControlPanel controlPanel;

struct UsTimezoneOption {
    const char* label;
    int32_t baseOffsetMinutes;  // standard time offset from UTC
};

static const UsTimezoneOption US_TIMEZONES[] = {
    {"US Pacific (PST/PDT)",  -480},  // UTC-8 base
    {"US Central (CST/CDT)",  -360},  // UTC-6 base
    {"US Eastern (EST/EDT)",  -300},  // UTC-5 base
};

static const int US_TIMEZONE_COUNT = sizeof(US_TIMEZONES) / sizeof(US_TIMEZONES[0]);

static uint16_t blend565(uint16_t from, uint16_t to, uint8_t amount) {
    uint16_t fr = (from >> 11) & 0x1F;
    uint16_t fg = (from >> 5) & 0x3F;
    uint16_t fb = from & 0x1F;
    uint16_t tr = (to >> 11) & 0x1F;
    uint16_t tg = (to >> 5) & 0x3F;
    uint16_t tb = to & 0x1F;

    uint16_t rr = (uint16_t)((fr * (255 - amount) + tr * amount) / 255);
    uint16_t rg = (uint16_t)((fg * (255 - amount) + tg * amount) / 255);
    uint16_t rb = (uint16_t)((fb * (255 - amount) + tb * amount) / 255);
    return (rr << 11) | (rg << 5) | rb;
}

static uint16_t lighten565(uint16_t color, uint8_t amount) {
    return blend565(color, COLOR_WHITE, amount);
}

static uint16_t darken565(uint16_t color, uint8_t amount) {
    return blend565(color, COLOR_BLACK, amount);
}

static void drawSurfaceButton(
    int x,
    int y,
    int w,
    int h,
    int r,
    uint16_t accent,
    const String& text,
    bool active,
    bool centered
);

static uint8_t pulseAmount(uint8_t maxAmount, unsigned long periodMs = 1400) {
    if (maxAmount == 0 || periodMs < 2) {
        return 0;
    }
    unsigned long half = periodMs / 2;
    unsigned long phase = millis() % periodMs;
    unsigned long ramp = phase <= half ? phase : (periodMs - phase);
    return (uint8_t)((ramp * maxAmount) / half);
}

static void drawGlowOrb(int cx, int cy, int radius, uint16_t fill, uint16_t border, bool pulsing) {
    uint8_t pulse = pulsing ? pulseAmount(60, 1600) : 0;
    uint16_t shell = darken565(fill, 70);
    uint16_t core = blend565(fill, COLOR_WHITE, 30 + pulse / 3);
    uint16_t gleam = lighten565(fill, 120 + pulse / 2);
    display.fillCircle(cx + 1, cy + 2, radius + 1, COLOR_BG_DARKER);
    display.fillCircle(cx, cy, radius, shell);
    if (radius > 1) {
        display.fillCircle(cx, cy, radius - 1, core);
    }
    display.drawCircle(cx, cy, radius, pulsing ? lighten565(border, pulse / 2) : border);
    if (radius > 2) {
        display.fillCircle(cx - 1, cy - 1, radius / 2, gleam);
    }
}

static void drawWiFiRow(int x, int y, int w, int h, const String& ssid, int rssi, bool secured, bool selected) {
    String label = ssid;
    if (label.length() > 18) {
        label = label.substring(0, 15) + "...";
    }

    uint16_t accent = selected ? COLOR_NEON_CYAN : COLOR_NEON_PURPLE;
    drawSurfaceButton(x, y, w, h, 6, accent, label, selected, false);

    uint16_t faceBg = selected ? blend565(COLOR_NEON_CYAN, COLOR_WHITE, 35) : COLOR_BG_DARK;
    uint16_t textColor = selected ? COLOR_BLACK : COLOR_WHITE;
    String signal = String(rssi) + " dBm";

    display.setTextSize(1);
    display.setTextDatum(MR_DATUM);
    display.setTextColor(textColor, faceBg);
    display.drawString(signal, x + w - 24, y + h / 2);

    drawGlowOrb(x + w - 11, y + h / 2, 4, secured ? COLOR_NEON_YELLOW : COLOR_GREEN, COLOR_WHITE, secured && selected);
}

static void drawSurfaceButton(
    int x,
    int y,
    int w,
    int h,
    int r,
    uint16_t accent,
    const String& text,
    bool active,
    bool centered
) {
    uint8_t pulse = active ? pulseAmount(42, 1500) : 0;
    uint16_t liveAccent = active ? lighten565(accent, pulse / 2) : accent;
    uint16_t shellColor = active ? darken565(liveAccent, 40) : COLOR_BG_MID;
    uint16_t faceTop = active ? lighten565(liveAccent, 110 + pulse / 3) : lighten565(COLOR_BG_MID, 55);
    uint16_t faceMid = active ? blend565(liveAccent, COLOR_WHITE, 35 + pulse / 4) : COLOR_BG_DARK;
    uint16_t faceBottom = active ? darken565(liveAccent, 55) : darken565(COLOR_BG_MID, 65);
    uint16_t outerBorder = active ? lighten565(liveAccent, 70 + pulse / 3) : accent;
    uint16_t innerBorder = active ? COLOR_WHITE : lighten565(COLOR_BG_MID, 85);
    uint16_t glossColor = active ? lighten565(liveAccent, 150 + pulse / 3) : lighten565(COLOR_BG_MID, 110);
    uint16_t lowlightColor = active ? darken565(liveAccent, 120) : darken565(COLOR_BG_MID, 110);
    uint16_t shadowFar = COLOR_BG_DARKER;
    uint16_t shadowNear = darken565(COLOR_BG_MID, 110);

    display.fillRoundRect(x + 3, y + 4, w, h, r, shadowFar);
    display.fillRoundRect(x + 2, y + 2, w, h, r, shadowNear);
    display.fillRoundRect(x, y, w, h, r, shellColor);

    int faceX = x + 2;
    int faceY = y + 2;
    int faceW = w - 4;
    int faceH = h - 4;
    int faceR = r > 2 ? r - 2 : 1;
    if (faceW > 0 && faceH > 0) {
        display.fillRoundRect(faceX, faceY, faceW, faceH, faceR, faceBottom);
        display.fillRoundRect(faceX + 1, faceY + 1, faceW - 2, faceH - 2, faceR > 1 ? faceR - 1 : 1, faceMid);
        int topH = (faceH * 60) / 100;
        if (topH < 3) topH = faceH;
        if (faceW > 6) {
            display.fillRoundRect(faceX + 2, faceY + 1, faceW - 4, topH, faceR > 2 ? faceR - 2 : 1, faceTop);
        }

        int glossW = faceW - 12;
        int glossH = faceH > 20 ? 6 : 4;
        if (glossW > 6) {
            display.fillRoundRect(faceX + 4, faceY + 3, glossW, glossH, 2, glossColor);
        }

        display.drawRoundRect(faceX, faceY, faceW, faceH, faceR, innerBorder);
        display.drawLine(faceX + 4, faceY + 2, faceX + faceW - 5, faceY + 2, glossColor);
        display.drawLine(faceX + 4, faceY + faceH - 3, faceX + faceW - 5, faceY + faceH - 3, lowlightColor);
    }

    display.drawRoundRect(x, y, w, h, r, outerBorder);

    uint16_t textColor = COLOR_WHITE;
    if (active && (accent == COLOR_NEON_CYAN || accent == COLOR_NEON_YELLOW || accent == COLOR_GREEN)) {
        textColor = COLOR_BLACK;
    }

    display.setTextSize(1);
    display.setTextDatum(centered ? MC_DATUM : ML_DATUM);
    display.setTextColor(textColor, faceMid);
    if (centered) {
        display.drawCentreString(text, x + w / 2, y + h / 2 + 1);
    } else {
        display.drawString(text, x + 10, y + h / 2);
    }
}

const char* ControlPanel::menuLabels[MENU_ITEMS] = {
    "WiFi Setup",
    "Bluetooth Pairing",
    "Rediscover Host",
    "Device Diagnostics",
    "Host Diagnostics",
    "Config Refresh",
    "Reconnect API",
    "Connection Mode",
    "Reset Pairing Only",
    "Reset WiFi Only",
    "Factory Reset",
    "New Pad Profile",
    "Time Settings",
    "Exit"
};

const ControlPanelAction ControlPanel::menuActions[MENU_ITEMS] = {
    ControlPanelAction::WIFI_SETUP,
    ControlPanelAction::BLUETOOTH_PAIRING, // shows BLE pairing PIN screen
    ControlPanelAction::PAIRING_SETUP,
    ControlPanelAction::DEVICE_DIAGNOSTICS,
    ControlPanelAction::HOST_DIAGNOSTICS,
    ControlPanelAction::CONFIG_REFRESH,
    ControlPanelAction::RECONNECT_API,
    ControlPanelAction::CONNECTION_MODE,
    ControlPanelAction::RESET_PAIRING,
    ControlPanelAction::RESET_WIFI,
    ControlPanelAction::FACTORY_RESET,
    ControlPanelAction::NEW_PROFILE,
    ControlPanelAction::TIME_SETTINGS,
    ControlPanelAction::EXIT
};

ControlPanel::ControlPanel() : selectedIndex(0), menuScrollRow(0), active(false), startupWindowStart(0) {}

bool ControlPanel::begin() {
    return true;
}

bool ControlPanel::showStartupWindow() {
    startupWindowStart = millis();

    unsigned long startTime = millis();
    Serial.println("[ControlPanel] Startup window waiting for touch...");
    while (millis() - startTime < STARTUP_CONTROL_PANEL_WINDOW_MS) {
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

        int remaining = (STARTUP_CONTROL_PANEL_WINDOW_MS - (millis() - startTime)) / 1000;
        String countStr = String(remaining) + "s";

        display.fillScreen(COLOR_BG_DARK);
        display.fillRect(0, 0, SCREEN_WIDTH, 28, COLOR_BG_DARKER);
        display.fillRect(0, SCREEN_HEIGHT - 22, SCREEN_WIDTH, 22, COLOR_BG_DARKER);
        display.drawLine(0, 0, SCREEN_WIDTH, 0, COLOR_NEON_PURPLE);
        display.drawLine(0, 27, SCREEN_WIDTH, 27, COLOR_NEON_CYAN);
        display.drawLine(0, SCREEN_HEIGHT - 23, SCREEN_WIDTH, SCREEN_HEIGHT - 23, COLOR_NEON_PURPLE);

        drawGlowOrb(SCREEN_WIDTH / 2, 46, 20, COLOR_NEON_PURPLE, COLOR_NEON_CYAN, true);

        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("DisplayPad", SCREEN_WIDTH / 2, 78);

        display.setTextSize(1);
        display.setTextColor(COLOR_NEON_CYAN, COLOR_BLACK);
        display.drawCentreString("Secure device console", SCREEN_WIDTH / 2, 98);

        drawSurfaceButton(50, 118, 220, 30, 6, COLOR_NEON_CYAN, "TOUCH FOR CONTROL PANEL", true, true);
        drawSurfaceButton(98, 160, 124, 36, 8, COLOR_NEON_YELLOW, countStr, true, true);

        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Startup window closes automatically", SCREEN_WIDTH / 2, 208);

        delay(100);
    }

    return false;  // Window expired, no action
}

ControlPanelAction ControlPanel::show() {
    Serial.println("[ControlPanel] show() called");
    selectedIndex = 0;
    menuScrollRow = 0;
    active = true;

    Serial.println("[ControlPanel] Drawing main menu...");
    drawMainMenu();
    Serial.println("[ControlPanel] Menu drawn, entering touch loop...");

    unsigned long lastAnimationFrame = millis();

    while (active) {
        int x, y;
        if (display.getTouch(&x, &y)) {
            delay(200);  // Debounce

            // Check for BACK button touch at top right
            if (handleBackButtonTouch(x, y)) {
                Serial.println("[ControlPanel] BACK button touched, closing");
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

            // Scrollbar region on the right (finger-friendly width)
            const int contentTop = 40;
            const int contentBottom = SCREEN_HEIGHT - 10;
            const int scrollBarWidth = 24;
            const int scrollRegionStartX = SCREEN_WIDTH - scrollBarWidth - 2;

            if (x >= scrollRegionStartX && x < SCREEN_WIDTH && y >= contentTop && y < contentBottom) {
                // Scrollbar drag region: while the finger is down in this strip,
                // map Y position to a scroll row so the menu scrolls with the
                // finger.
                int totalRows = (MENU_ITEMS + 1) / 2;
                const int visibleRows = 3;
                if (totalRows > visibleRows) {
                    int maxOffset = totalRows - visibleRows;
                    int lastScroll = menuScrollRow;

                    int sx = x;
                    int sy = y;
                    while (display.getTouch(&sx, &sy)) {
                        if (sy < contentTop) sy = contentTop;
                        if (sy > contentBottom - 1) sy = contentBottom - 1;

                        int trackHeight = contentBottom - contentTop;
                        int relY = sy - contentTop;
                        int newOffset = (int)((relY * maxOffset) / (float)trackHeight + 0.5f);
                        if (newOffset < 0) newOffset = 0;
                        if (newOffset > maxOffset) newOffset = maxOffset;

                        if (newOffset != menuScrollRow) {
                            menuScrollRow = newOffset;
                            drawMainMenu();
                        }

                        delay(10);
                    }
                }
            } else {
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
        } else if (millis() - lastAnimationFrame >= 120) {
            drawMainMenu();
            lastAnimationFrame = millis();
        }

        delay(10);
    }

    return ControlPanelAction::NONE;
}

void ControlPanel::drawSubscreenHeader(const String& title) {
    display.fillRect(0, 0, SCREEN_WIDTH, 30, COLOR_BG_DARKER);
    display.drawLine(0, 0, SCREEN_WIDTH, 0, COLOR_NEON_PURPLE);
    display.drawLine(0, 29, SCREEN_WIDTH, 29, COLOR_NEON_CYAN);
    display.setTextSize(2);
    display.setTextDatum(MC_DATUM);
    display.setTextColor(COLOR_NEON_CYAN, COLOR_BG_DARKER);
    display.drawCentreString(title, SCREEN_WIDTH/2, 15);

    int backW = 50;
    int backH = 18;
    int backX = SCREEN_WIDTH - backW - 4;
    int backY = 6;
    drawSurfaceButton(backX, backY, backW, backH, 4, COLOR_NEON_YELLOW, "BACK", false, true);
}

bool ControlPanel::handleBackButtonTouch(int x, int y) {
    return (y < 30 && x > SCREEN_WIDTH - 60);
}

void ControlPanel::drawMainMenu() {
    Serial.println("[ControlPanel] drawMainMenu() starting...");
    display.clear();

    // Title + BACK in header
    drawSubscreenHeader("Control Panel");

    // 2-column grid of buttons with vertical scrolling
    const int contentTop = 40;
    const int contentBottom = SCREEN_HEIGHT - 10;
    const int contentHeight = contentBottom - contentTop;

    const int rowsVisible = 3;   // 3 rows * 2 columns = 6 items visible
    const int totalRows = (MENU_ITEMS + 1) / 2;
    const int rowHeight = contentHeight / rowsVisible;  // evenly divide space

    const int colCount = 2;
    const int colGap = 6;
    const int scrollBarWidth = 24;  // wider, finger-friendly scrollbar

    int usableWidth = SCREEN_WIDTH - 10 - scrollBarWidth;  // leave margin + scrollbar
    int colWidth = (usableWidth - colGap) / colCount;
    int colX0 = 5;

    for (int row = 0; row < rowsVisible; ++row) {
        int globalRow = menuScrollRow + row;
        int baseIndex = globalRow * 2;
        int y = contentTop + row * rowHeight + 4;
        int h = rowHeight - 8;

        if (baseIndex >= MENU_ITEMS) break;

        // Left column
        int xLeft = colX0;
        drawMenuItem(xLeft, y, colWidth, h, menuLabels[baseIndex], baseIndex == selectedIndex);

        // Right column (if exists)
        int rightIndex = baseIndex + 1;
        if (rightIndex < MENU_ITEMS) {
            int xRight = colX0 + colWidth + colGap;
            drawMenuItem(xRight, y, colWidth, h, menuLabels[rightIndex], rightIndex == selectedIndex);
        }
    }

    // Draw scrollbar track and thumb on the right
    if (totalRows > rowsVisible) {
        int trackX = SCREEN_WIDTH - scrollBarWidth - 2;
        display.fillRect(trackX, contentTop, scrollBarWidth, contentHeight, COLOR_BG_MID);

        int thumbHeight = max(10, (contentHeight * rowsVisible) / totalRows);
        int maxOffset = totalRows - rowsVisible;
        int thumbY = contentTop;
        if (maxOffset > 0) {
            thumbY = contentTop + (contentHeight - thumbHeight) * menuScrollRow / maxOffset;
        }

        display.fillRect(trackX, thumbY, scrollBarWidth, thumbHeight, COLOR_NEON_CYAN);
    }

    Serial.println("[ControlPanel] drawMainMenu() complete");
}

void ControlPanel::drawMenuItem(int x, int y, int w, int h, const String& text, bool selected) {
    drawSurfaceButton(x, y, w, h, 5, selected ? COLOR_NEON_CYAN : COLOR_NEON_PURPLE, text, selected, false);
}

int ControlPanel::getMenuItemAt(int x, int y) {
    const int contentTop = 40;
    const int contentBottom = SCREEN_HEIGHT - 10;
    const int contentHeight = contentBottom - contentTop;
    const int rowsVisible = 3;
    const int totalRows = (MENU_ITEMS + 1) / 2;
    const int scrollBarWidth = 24;
    const int scrollRegionStartX = SCREEN_WIDTH - scrollBarWidth - 2;

    // Only treat taps in the left content area (excluding the scrollbar strip)
    if (y < contentTop || y >= contentBottom || x < 5 || x >= scrollRegionStartX) {
        return -1;
    }

    int rowHeight = contentHeight / rowsVisible;
    int localRow = (y - contentTop) / rowHeight;
    int globalRow = menuScrollRow + localRow;
    if (globalRow < 0 || globalRow >= totalRows) {
        return -1;
    }

    const int colCount = 2;
    const int colGap = 6;
    int usableWidth = SCREEN_WIDTH - 10 - scrollBarWidth;
    int colWidth = (usableWidth - colGap) / colCount;
    int colX0 = 5;

    int indexLeft = globalRow * 2;
    int indexRight = indexLeft + 1;

    // Check left column
    int xLeft = colX0;
    if (x >= xLeft && x < xLeft + colWidth) {
        if (indexLeft < MENU_ITEMS) return indexLeft;
    }

    // Check right column
    int xRight = colX0 + colWidth + colGap;
    if (x >= xRight && x < xRight + colWidth) {
        if (indexRight < MENU_ITEMS) return indexRight;
    }

    return -1;
}

void ControlPanel::executeAction(ControlPanelAction action) {
    switch (action) {
        case ControlPanelAction::WIFI_SETUP:
            showWiFiSetup();
            break;
        case ControlPanelAction::BLUETOOTH_PAIRING:
            showPairingSetup();
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
        case ControlPanelAction::CONNECTION_MODE:
            showConnectionModeSettings();
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
        case ControlPanelAction::TIME_SETTINGS:
            showTimeSettings();
            break;
        default:
            break;
    }
}

void ControlPanel::showConnectionModeSettings() {
    // Start with the currently stored mode, allow the user to change the
    // selection, and only persist it when they tap APPLY.
    ConnectionMode selected = getConnectionMode();
    bool done = false;

    while (!done) {
        display.clear();
        drawSubscreenHeader("Connection Mode");

        const char* modeLabel = "Auto (BLE + WiFi)";
        if (selected == ConnectionMode::WIFI) {
            modeLabel = "WiFi only";
        } else if (selected == ConnectionMode::BLUETOOTH) {
            modeLabel = "Bluetooth only";
        }

        display.setTextSize(1);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Choose connection mode, then tap APPLY", SCREEN_WIDTH/2, 45);

        display.setTextSize(1);
        display.setTextColor(COLOR_NEON_CYAN, COLOR_BLACK);
        display.drawCentreString(String("Current: ") + modeLabel, SCREEN_WIDTH/2, 65);

        // Compact three-option layout that fits within the 240px height.
        int btnW = SCREEN_WIDTH - 40;   // 40px total horizontal margin
        int btnH = 24;                  // shorter buttons to fit 4 rows
        int btnX = 20;
        int wifiY = 90;
        int btY = wifiY + btnH + 6;
        int autoY = btY + btnH + 6;
        int applyY = autoY + btnH + 10;

        // WiFi option
        uint16_t wifiBorder = (selected == ConnectionMode::WIFI)
                                  ? COLOR_NEON_CYAN
                                  : COLOR_NEON_PURPLE;
        drawSurfaceButton(btnX, wifiY, btnW, btnH, 4, wifiBorder, "WiFi only (HTTP/WebSocket)", selected == ConnectionMode::WIFI, false);

        // Bluetooth option
        uint16_t btBorder = (selected == ConnectionMode::BLUETOOTH)
                                ? COLOR_NEON_CYAN
                                : COLOR_NEON_PURPLE;
        drawSurfaceButton(btnX, btY, btnW, btnH, 4, btBorder, "Bluetooth only (BLE bridge)", selected == ConnectionMode::BLUETOOTH, false);

        // Auto option
        uint16_t autoBorder = (selected == ConnectionMode::AUTO)
                                  ? COLOR_NEON_CYAN
                                  : COLOR_NEON_PURPLE;
        drawSurfaceButton(btnX, autoY, btnW, btnH, 4, autoBorder, "Auto (prefer BLE, fallback WiFi)", selected == ConnectionMode::AUTO, false);

        // Apply button
        int applyH = 26;
        // Use neon cyan for the APPLY button background so it stands out.
        drawSurfaceButton(btnX, applyY, btnW, applyH, 5, COLOR_NEON_CYAN, "APPLY", true, true);

        int tx, ty;
        bool touched = false;
        unsigned long frameStart = millis();
        while (!display.getTouch(&tx, &ty)) {
            if (millis() - frameStart >= 120) {
                break;
            }
            delay(10);
        }
        touched = display.getTouch(&tx, &ty);
        if (!touched) {
            continue;
        }

        if (handleBackButtonTouch(tx, ty)) {
            done = true;
            continue;
        }

        if (tx >= btnX && tx < btnX + btnW) {
            if (ty >= wifiY && ty < wifiY + btnH) {
                selected = ConnectionMode::WIFI;
            } else if (ty >= btY && ty < btY + btnH) {
                selected = ConnectionMode::BLUETOOTH;
            } else if (ty >= autoY && ty < autoY + btnH) {
                selected = ConnectionMode::AUTO;
            } else if (ty >= applyY && ty < applyY + applyH) {
                setConnectionMode(selected);
                done = true;
            }
        }
    }
}

void ControlPanel::showWiFiSetup() {
    // First, if we already have saved WiFi credentials, show a summary screen
    // with current SSID, password, and status, plus CONNECT and EDIT buttons.
    String savedSSID = storage.getWiFiSSID();
    String savedPass = storage.getWiFiPass();

    if (savedSSID.length() > 0) {
        bool inOverview = true;

        while (inOverview) {
            display.clear();
            drawSubscreenHeader("WiFi Setup");

            display.setTextSize(2);
            display.setTextDatum(TC_DATUM);
            display.setTextColor(COLOR_WHITE, COLOR_BLACK);
            display.drawCentreString("Current WiFi", SCREEN_WIDTH/2, 42);

            display.setTextSize(1);
            display.setTextDatum(TL_DATUM);
            display.setTextColor(COLOR_WHITE, COLOR_BLACK);
            int infoX = 20;
            int infoY = 70;
            display.drawString("SSID: " + savedSSID, infoX, infoY);
            infoY += 16;

            String passLabel;
            if (savedPass.length() > 0) {
                // Show password as asterisks so it is not exposed on-screen.
                passLabel = "";
                for (size_t i = 0; i < savedPass.length(); ++i) {
                    passLabel += '*';
                }
            } else {
                passLabel = String("<not set>");
            }
            display.drawString("Password: " + passLabel, infoX, infoY);
            infoY += 16;

            // Status and signal
            if (wifiManager.isConnected()) {
                int rssi = wifiManager.getRSSI();
                display.drawString("Status: Connected", infoX, infoY);
                infoY += 14;
                display.drawString("Signal: " + String(rssi) + " dBm", infoX, infoY);
            } else {
                display.drawString("Status: Not connected", infoX, infoY);
            }

            // Buttons at bottom: CONNECT and EDIT
            int btnY = SCREEN_HEIGHT - 40;
            int btnW = (SCREEN_WIDTH - 60) / 2;
            int connectX = 20;
            int editX = connectX + btnW + 20;
            int btnH = 26;

            // CONNECT button
            drawSurfaceButton(connectX, btnY, btnW, btnH, 5, COLOR_GREEN, "CONNECT", true, true);

            drawSurfaceButton(editX, btnY, btnW, btnH, 5, COLOR_NEON_PURPLE, "EDIT", false, true);

            int tx, ty;
            bool touched = false;
            unsigned long frameStart = millis();
            while (!display.getTouch(&tx, &ty)) {
                if (millis() - frameStart >= 120) {
                    break;
                }
                delay(10);
            }
            touched = display.getTouch(&tx, &ty);
            if (!touched) {
                continue;
            }

            if (handleBackButtonTouch(tx, ty)) {
                return;
            }

            // CONNECT
            if (tx >= connectX && tx < connectX + btnW && ty >= btnY && ty < btnY + btnH) {
                display.clear();
                drawSubscreenHeader("WiFi Setup");
                display.setTextSize(2);
                display.setTextDatum(TC_DATUM);
                display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                display.drawCentreString("Connecting...", SCREEN_WIDTH/2, 70);
                display.setTextSize(1);
                display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
                display.drawCentreString(savedSSID, SCREEN_WIDTH/2, 110);

                bool ok = wifiManager.connect(savedSSID, savedPass);

                display.clear();
                drawSubscreenHeader("WiFi Setup");
                display.setTextSize(2);
                display.setTextDatum(TC_DATUM);

                if (ok) {
                    display.setTextColor(COLOR_GREEN, COLOR_BLACK);
                    display.drawCentreString("Connected!", SCREEN_WIDTH/2, 80);
                    display.setTextSize(1);
                    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                    display.drawCentreString(wifiManager.getIP(), SCREEN_WIDTH/2, 120);
                } else {
                    display.setTextColor(COLOR_RED, COLOR_BLACK);
                    display.drawCentreString("Failed!", SCREEN_WIDTH/2, 80);
                    display.setTextSize(1);
                    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                    display.drawCentreString("Check WiFi and try again", SCREEN_WIDTH/2, 120);
                }

                display.drawCentreString("Touch to go back", SCREEN_WIDTH/2, 160);
                int cx, cy;
                while (!display.getTouch(&cx, &cy)) { delay(10); }
                return;
            }

            // EDIT -> break to full scan UI
            if (tx >= editX && tx < editX + btnW && ty >= btnY && ty < btnY + btnH) {
                inOverview = false;
            }
        }
    }

    // No saved network or user chose EDIT: perform full scan UI
    // Scan for WiFi networks
    display.clear();
    drawSubscreenHeader("WiFi Setup");

    display.setTextSize(1);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString("Scanning...", SCREEN_WIDTH/2, 50);

    Serial.println("[WiFi] Scanning for networks...");
    int numNetworks = WiFi.scanNetworks();
    Serial.println("[WiFi] Found " + String(numNetworks) + " networks");

    if (numNetworks == 0) {
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        display.drawCentreString("No networks found", SCREEN_WIDTH/2, 80);
        display.drawCentreString("Touch to go back", SCREEN_WIDTH/2, 100);

        int tx, ty;
        while (!display.getTouch(&tx, &ty)) { delay(10); }
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
        drawSubscreenHeader("Select WiFi");

        display.setTextSize(2);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Select WiFi", SCREEN_WIDTH/2, 35);

        // Draw networks
        display.setTextSize(1);
        for (int i = 0; i < visibleNetworks && (topIndex + i) < numNetworks; i++) {
            int idx = topIndex + i;
            int y = 45 + i * 30;
            String ssid = WiFi.SSID(idx);
            int rssi = WiFi.RSSI(idx);
            bool secured = WiFi.encryptionType(idx) != WIFI_AUTH_OPEN;
            drawWiFiRow(6, y, SCREEN_WIDTH - 16, 26, ssid, rssi, secured, idx == selectedIndex);
        }

        // Instructions
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Tap network to select", SCREEN_WIDTH/2, 190);

        // Wait for touch
        int tx, ty;
        bool touched = false;
        unsigned long frameStart = millis();
        while (!display.getTouch(&tx, &ty)) {
            if (millis() - frameStart >= 120) {
                break;
            }
            delay(10);
        }
        touched = display.getTouch(&tx, &ty);
        if (!touched) {
            continue;
        }

        if (handleBackButtonTouch(tx, ty)) {
            return;
        }

        // Check for scroll (top/bottom area)
        if (ty < 45) {
            // Scroll up
            if (selectedIndex > 0) {
                selectedIndex--;
                if (selectedIndex < topIndex) topIndex = selectedIndex;
            }
        } else if (ty > 180) {
            // Scroll down
            if (selectedIndex < numNetworks - 1) {
                selectedIndex++;
                if (selectedIndex >= topIndex + visibleNetworks) topIndex++;
            }
        } else {
            // Check which network was tapped
            int tappedIndex = (ty - 45) / 30 + topIndex;
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

    // Connect to WiFi using the central WiFiManager so state, DNS, and NTP are
    // configured consistently.
    display.clear();
    drawSubscreenHeader("WiFi Setup");

    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Connecting...", SCREEN_WIDTH/2, 70);

    display.setTextSize(1);
    display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
    display.drawCentreString(selectedSSID, SCREEN_WIDTH/2, 110);

    Serial.println("[WiFi] Connecting to " + selectedSSID + " via WiFiManager...");

    bool ok = wifiManager.connect(selectedSSID, password);

    WiFi.scanDelete();

    display.clear();
    drawSubscreenHeader("WiFi Setup");
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);

    if (ok) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawCentreString("Connected!", SCREEN_WIDTH/2, 80);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString(wifiManager.getIP(), SCREEN_WIDTH/2, 120);
    } else {
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        display.drawCentreString("Failed!", SCREEN_WIDTH/2, 80);
        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Check password and try again", SCREEN_WIDTH/2, 120);
    }

    display.drawCentreString("Touch to go back", SCREEN_WIDTH/2, 160);
    int tx2, ty2;
    while (!display.getTouch(&tx2, &ty2)) { delay(10); }
    delay(300);
}

void ControlPanel::showPairingSetup() {
    display.clear();
    drawSubscreenHeader("Bluetooth Pairing");

    // Clear any stale bonds so a host that paired with previous firmware (and
    // now has mismatched keys) is forced to pair fresh, then generate a new
    // passkey and apply it to the NimBLE security configuration so the value
    // shown here matches what the host must enter.
    btManager.clearBonds();
    String pin = btManager.startPairingSession();

    display.setTextSize(1);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("On your PC, enter this PIN", SCREEN_WIDTH/2, 42);

    // Large, easy-to-read PIN
    display.setTextSize(3);
    display.setTextColor(COLOR_NEON_CYAN, COLOR_BLACK);
    display.drawCentreString(pin, SCREEN_WIDTH/2, 70);

    // BLE device name so the user can identify the pad in the Windows list
    String uuid = storage.getPadUUID();
    String suffix = uuid.length() >= 4 ? uuid.substring(0, 4) : uuid;
    String devName = String("DisplayPad-") + suffix;

    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Device: " + devName, SCREEN_WIDTH/2, 120);

    if (storage.isPaired()) {
        display.setTextColor(COLOR_GREEN, COLOR_BLACK);
        display.drawCentreString("Status: Paired", SCREEN_WIDTH/2, 140);
    } else {
        display.setTextColor(COLOR_YELLOW, COLOR_BLACK);
        display.drawCentreString("Status: Not Paired", SCREEN_WIDTH/2, 140);
    }

    display.setTextColor(COLOR_GRAY, COLOR_BLACK);
    display.drawCentreString("Touch to go back", SCREEN_WIDTH/2, 165);

    // Wait for touch to go back
    int tx, ty;
    while (!display.getTouch(&tx, &ty)) {
        delay(10);
    }
}

void ControlPanel::showDeviceDiagnostics() {
    display.clear();
    drawSubscreenHeader("Device Status");

    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Device Status", SCREEN_WIDTH/2, 50);

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

    // Wait for touch to go back
    int tx, ty;
    while (!display.getTouch(&tx, &ty)) {
        delay(10);
    }
}

void ControlPanel::showHostDiagnostics() {
    display.clear();
    drawSubscreenHeader("Host Status");

    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString("Host Status", SCREEN_WIDTH/2, 50);

    display.setTextSize(1);

    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawString("API Host: " + storage.getApiHost(), 20, 60);
    display.drawString("API IP: " + storage.getApiIP(), 20, 85);
    display.drawString("API Port: " + String(storage.getApiPort()), 20, 110);
    display.drawString("Config Ver: " + String(storage.getConfigVersion()), 20, 135);

    // Wait for touch to go back
    int tx, ty;
    while (!display.getTouch(&tx, &ty)) {
        delay(10);
    }
}

void ControlPanel::showTimeSettings() {
    bool done = false;

    while (!done) {
        display.clear();
        drawSubscreenHeader("Time Settings");

        int32_t offset = storage.getTimeOffsetMinutes();
        bool autoUsDst = storage.getUseUsAutoDst();

        // Show current base offset and matching US timezone if any
        display.setTextSize(1);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString("Select US timezone or adjust offset", SCREEN_WIDTH/2, 45);

        String offStr = String(offset) + " min";
        display.setTextSize(2);
        display.setTextColor(COLOR_NEON_CYAN, COLOR_BLACK);
        display.drawCentreString(offStr, SCREEN_WIDTH/2, 70);

        // Try to find a matching predefined US region when auto DST is enabled
        const char* zoneLabel = autoUsDst ? "US Custom" : "Custom";
        if (autoUsDst && offset != 0) {
            for (int i = 0; i < US_TIMEZONE_COUNT; ++i) {
                if (US_TIMEZONES[i].baseOffsetMinutes == offset) {
                    zoneLabel = US_TIMEZONES[i].label;
                    break;
                }
            }
        } else if (!autoUsDst && offset == 0) {
            zoneLabel = "Server timezone";
        }

        display.setTextSize(1);
        display.setTextColor(COLOR_WHITE, COLOR_BLACK);
        display.drawCentreString(String("Current: ") + zoneLabel, SCREEN_WIDTH/2, 95);

        // Button: open US timezone list
        int listBtnX = 20;
        int listBtnY = 120;
        int listBtnW = SCREEN_WIDTH - 40;
        int listBtnH = 30;
        display.fillRoundRect(listBtnX, listBtnY, listBtnW, listBtnH, 5, COLOR_BG_MID);
        display.drawRoundRect(listBtnX, listBtnY, listBtnW, listBtnH, 5, COLOR_NEON_PURPLE);
        display.setTextColor(COLOR_WHITE, COLOR_BG_MID);
        display.setTextDatum(MC_DATUM);
        display.drawCentreString("Choose US Timezone (scroll)", SCREEN_WIDTH/2, listBtnY + listBtnH/2);

        // Button: reset to server timezone
        int resetY = listBtnY + listBtnH + 10;
        display.fillRoundRect(listBtnX, resetY, listBtnW, listBtnH, 5, COLOR_BG_MID);
        display.drawRoundRect(listBtnX, resetY, listBtnW, listBtnH, 5, COLOR_NEON_YELLOW);
        display.setTextColor(COLOR_WHITE, COLOR_BG_MID);
        display.drawCentreString("Reset to server timezone", SCREEN_WIDTH/2, resetY + listBtnH/2);

        int tx, ty;
        while (!display.getTouch(&tx, &ty)) {
            delay(10);
        }

        if (handleBackButtonTouch(tx, ty)) {
            done = true;
            continue;
        }

        // Open US timezone picker
        if (ty >= listBtnY && ty < listBtnY + listBtnH &&
            tx >= listBtnX && tx < listBtnX + listBtnW) {

            int selectedIndex = 0;
            int topIndex = 0;
            const int visible = 4;
            bool choosing = true;

            while (choosing) {
                display.clear();
                drawSubscreenHeader("US Timezones");

                display.setTextSize(1);
                display.setTextDatum(TC_DATUM);
                display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                display.drawCentreString("Tap a timezone to select", SCREEN_WIDTH/2, 40);

                // Draw list
                int listStartY = 55;
                int rowH = 28;

                for (int i = 0; i < visible && (topIndex + i) < US_TIMEZONE_COUNT; ++i) {
                    int idx = topIndex + i;
                    int y = listStartY + i * rowH;

                    bool sel = (idx == selectedIndex);
                    uint16_t bg = sel ? COLOR_ACCENT : COLOR_DARK_GRAY;
                    uint16_t fg = sel ? COLOR_BLACK : COLOR_WHITE;

                    display.fillRect(5, y, SCREEN_WIDTH - 10, rowH - 2, bg);
                    display.drawRect(5, y, SCREEN_WIDTH - 10, rowH - 2, COLOR_GRAY);
                    display.setTextDatum(ML_DATUM);
                    display.setTextColor(fg, bg);
                    display.drawString(US_TIMEZONES[idx].label, 10, y + (rowH - 2) / 2);
                }

                // Hint / scroll areas
                display.setTextDatum(TC_DATUM);
                display.setTextColor(COLOR_WHITE, COLOR_BLACK);
                display.drawCentreString("Tap top/bottom to scroll", SCREEN_WIDTH/2, 55 + visible * rowH);

                int lx, ly;
                while (!display.getTouch(&lx, &ly)) {
                    delay(10);
                }

                if (handleBackButtonTouch(lx, ly)) {
                    choosing = false;
                    break;
                }

                int listEndY = listStartY + visible * rowH;
                if (ly < listStartY) {
                    // Scroll up
                    if (selectedIndex > 0) {
                        selectedIndex--;
                        if (selectedIndex < topIndex) topIndex = selectedIndex;
                    }
                } else if (ly > listEndY) {
                    // Scroll down
                    if (selectedIndex < US_TIMEZONE_COUNT - 1) {
                        selectedIndex++;
                        if (selectedIndex >= topIndex + visible) topIndex++;
                    }
                } else {
                    // Inside list: select tapped row
                    int tapped = (ly - listStartY) / rowH + topIndex;
                    if (tapped >= 0 && tapped < US_TIMEZONE_COUNT) {
                        selectedIndex = tapped;
                        offset = US_TIMEZONES[selectedIndex].baseOffsetMinutes;
                        storage.setTimeOffsetMinutes(offset);
                        storage.setUseUsAutoDst(true);
                        choosing = false;
                    }
                }
            }
        } else if (ty >= resetY && ty < resetY + listBtnH &&
                   tx >= listBtnX && tx < listBtnX + listBtnW) {
            // Reset to server-provided timezone (store 0) and disable US auto DST
            storage.setTimeOffsetMinutes(0);
            storage.setUseUsAutoDst(false);
        }
    }
}

bool ControlPanel::confirmReset(const String& title, const String& message) {
    // Draw a centered modal confirmation box with explicit YES / NO buttons.
    display.clear();
    display.fillScreen(COLOR_BG_DARK);

    int boxW = 260;
    int boxH = 140;
    int boxX = (SCREEN_WIDTH - boxW) / 2;
    int boxY = (SCREEN_HEIGHT - boxH) / 2;

    // Box background and border
    display.fillRoundRect(boxX + 4, boxY + 5, boxW, boxH, 8, COLOR_BG_DARKER);
    display.fillRoundRect(boxX, boxY, boxW, boxH, 8, COLOR_BG_MID);
    display.fillRoundRect(boxX + 2, boxY + 2, boxW - 4, boxH - 4, 6, COLOR_BG_DARK);
    display.drawRoundRect(boxX, boxY, boxW, boxH, 8, COLOR_NEON_PURPLE);
    display.drawRoundRect(boxX + 2, boxY + 2, boxW - 4, boxH - 4, 6, COLOR_NEON_CYAN);

    // Title in red near top of box
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_RED, COLOR_BG_MID);
    display.drawCentreString(title, SCREEN_WIDTH / 2, boxY + 18);

    // Message text in white
    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_BG_MID);
    display.drawCentreString(message, SCREEN_WIDTH / 2, boxY + 48);

    // YES / NO buttons at bottom of the box
    int btnMargin = 14;
    int btnH = 28;
    int btnY = boxY + boxH - btnH - btnMargin;
    int btnW = (boxW - (3 * btnMargin)) / 2;

    int noX = boxX + btnMargin;
    int yesX = noX + btnW + btnMargin;

    // NO button (red accent)
    drawSurfaceButton(noX, btnY, btnW, btnH, 6, COLOR_RED, "NO", true, true);

    drawSurfaceButton(yesX, btnY, btnW, btnH, 6, COLOR_GREEN, "YES", true, true);

    // Allow up to 5 seconds for a decision; otherwise auto-cancel and let the
    // caller redraw the previous screen.
    unsigned long start = millis();

    while (true) {
        int tx = 0, ty = 0;
        bool touched = false;

        // Wait for a touch or timeout
        while (millis() - start < 5000) {
            if (display.getTouch(&tx, &ty)) {
                touched = true;
                break;
            }
            delay(10);
        }

        if (!touched) {
            // Timed out without a choice -> treat as NO
            return false;
        }

        // YES hit-test
        if (tx >= yesX && tx < yesX + btnW && ty >= btnY && ty < btnY + btnH) {
            return true;
        }

        // NO hit-test (or tap outside the box cancels)
        if ((tx >= noX && tx < noX + btnW && ty >= btnY && ty < btnY + btnH) ||
            tx < boxX || tx >= boxX + boxW || ty < boxY || ty >= boxY + boxH) {
            return false;
        }
        // Otherwise (e.g. tapped message area), loop again and keep dialog up
    }
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
