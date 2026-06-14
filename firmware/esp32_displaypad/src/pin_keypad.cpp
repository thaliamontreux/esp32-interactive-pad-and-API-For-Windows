#include "pin_keypad.h"
#include "storage.h"
#include <mbedtls/sha256.h>

PINKeypad pinKeypad;

const char* PINKeypad::keys[KEY_ROWS][KEY_COLS] = {
    {"1", "2", "3"},
    {"4", "5", "6"},
    {"7", "8", "9"},
    {"0", "CLR", "ENT"}
};

PINKeypad::PINKeypad() : active(false), attempts(0), maxAttempts(5), lockoutUntil(0) {}

bool PINKeypad::begin() {
    return true;
}

PINResult PINKeypad::enterPIN(String& outPIN, const String& prompt, int maxAtt) {
    Serial.println("[PINKeypad] enterPIN called with prompt: " + prompt);

    if (maxAtt > 0) maxAttempts = maxAtt;

    // Check lockout
    if (millis() < lockoutUntil) {
        Serial.println("[PINKeypad] Locked out");
        return PINResult::LOCKED;
    }

    currentPIN = "";
    promptText = prompt;
    active = true;
    attempts = 0;

    Serial.println("[PINKeypad] Clearing display and drawing keypad...");
    display.clear();
    drawPINDisplay();
    drawKeypad();
    Serial.println("[PINKeypad] Keypad drawn, waiting for input...");

    unsigned long startTime = millis();
    const unsigned long timeout = 60000;  // 60 second timeout

    while (active) {
        // Check timeout
        if (millis() - startTime > timeout) {
            active = false;
            return PINResult::CANCELLED;
        }

        // Handle touch
        int tx, ty;
        if (display.getTouch(&tx, &ty)) {
            Serial.println("[PINKeypad] Touch at x=" + String(tx) + " y=" + String(ty));
            int key = getKeyAt(tx, ty);
            Serial.println("[PINKeypad] Key detected: " + String(key));
            if (key >= 0) {
                delay(200);  // Debounce

                if (key < 10) {
                    // Digit key
                    if (currentPIN.length() < PIN_MAX_LENGTH) {
                        currentPIN += String(key);
                        updateDisplay();
                    }
                } else if (key == 10) {
                    // CLR
                    Serial.println("[PINKeypad] CLR pressed");
                    currentPIN = "";
                    updateDisplay();
                } else if (key == 11) {
                    // ENT
                    Serial.println("[PINKeypad] ENT pressed");
                    // ENT
                    if (currentPIN.length() > 0) {
                        // Check if PIN is valid
                        if (validatePIN(currentPIN)) {
                            outPIN = currentPIN;
                            attempts = 0;
                            active = false;
                            return PINResult::SUCCESS;
                        } else {
                            attempts++;
                            currentPIN = "";
                            updateDisplay();

                            if (attempts >= maxAttempts) {
                                lockoutUntil = millis() + (PIN_LOCKOUT_SECONDS * 1000);
                                active = false;
                                return PINResult::LOCKED;
                            }
                        }
                    }
                }
            }
        }

        delay(10);
    }

    return PINResult::CANCELLED;
}

bool PINKeypad::getNumericInput(String& outInput, const String& prompt, int maxDigits) {
    Serial.println("[PINKeypad] getNumericInput called for: " + prompt);

    active = true;
    currentPIN = "";
    promptText = prompt;

    Serial.println("[PINKeypad] Clearing display and drawing keypad...");
    display.clear();
    drawPINDisplay();
    drawKeypad();
    Serial.println("[PINKeypad] Keypad drawn, waiting for input...");

    unsigned long startTime = millis();
    const unsigned long timeout = 120000;  // 2 minute timeout for pairing

    while (active) {
        // Check timeout
        if (millis() - startTime > timeout) {
            active = false;
            Serial.println("[PINKeypad] Timeout");
            return false;
        }

        // Handle touch
        int tx, ty;
        if (display.getTouch(&tx, &ty)) {
            Serial.println("[PINKeypad] Touch at x=" + String(tx) + " y=" + String(ty));
            int key = getKeyAt(tx, ty);
            Serial.println("[PINKeypad] Key detected: " + String(key));
            if (key >= 0) {
                delay(200);  // Debounce

                if (key >= 0 && key <= 9) {
                    // Digit keys
                    if (currentPIN.length() < maxDigits) {
                        Serial.println("[PINKeypad] Digit " + String(key) + " pressed");
                        currentPIN += String(key);
                        updateDisplay();
                    }
                } else if (key == 10) {
                    // CLR
                    Serial.println("[PINKeypad] CLR pressed");
                    currentPIN = "";
                    updateDisplay();
                } else if (key == 11) {
                    // ENT - return the entered code
                    Serial.println("[PINKeypad] ENT pressed, returning: " + currentPIN);
                    if (currentPIN.length() > 0) {
                        outInput = currentPIN;
                        active = false;
                        return true;
                    }
                }
            }
        }

        delay(10);
    }

    return false;
}

bool PINKeypad::validatePIN(const String& pin) {
    // For now, validate against default or check with server
    // Simplified: accept default PIN or any 8-digit PIN
    if (pin == DEFAULT_PIN) return true;

    // Check length
    if (pin.length() != PIN_MAX_LENGTH) return false;

    // Check if all digits
    for (int i = 0; i < pin.length(); i++) {
        if (!isdigit(pin[i])) return false;
    }

    return true;
}

bool PINKeypad::setPIN(const String& newPIN) {
    if (newPIN.length() < 4 || newPIN.length() > PIN_MAX_LENGTH) return false;

    // Hash the PIN (simplified hash)
    uint8_t hash[32];
    mbedtls_sha256((const uint8_t*)newPIN.c_str(), newPIN.length(), hash, 0);

    char hashStr[65];
    for (int i = 0; i < 32; i++) {
        sprintf(&hashStr[i * 2], "%02X", hash[i]);
    }

    return storage.setPINHash(hashStr);
}

void PINKeypad::resetToDefault() {
    storage.setPINHash("");
}

bool PINKeypad::isDefaultPIN() {
    return storage.getPINHash().length() == 0;
}

void PINKeypad::drawKeypad() {
    // Layout: 2 rows of 5 keys each
    // Row 0: 1 2 3 4 5
    // Row 1: 6 7 8 9 0
    // Row 2: [CLR] [ENT]

    const char* row0[5] = {"1", "2", "3", "4", "5"};
    const char* row1[5] = {"6", "7", "8", "9", "0"};

    int startX = (SCREEN_WIDTH - (5 * KEY_W + 4 * KEY_SPACING)) / 2;
    int startY = 70;  // Below PIN display

    display.setTextSize(2);
    display.setTextDatum(MC_DATUM);

    // Draw row 0: 1-5
    for (int col = 0; col < 5; col++) {
        int x = startX + col * (KEY_W + KEY_SPACING);
        int y = startY;

        display.fillRoundRect(x, y, KEY_W, KEY_H, 5, COLOR_BUTTON_BG);
        display.drawRoundRect(x, y, KEY_W, KEY_H, 5, COLOR_WHITE);
        display.setTextColor(COLOR_WHITE, COLOR_BUTTON_BG);
        display.drawCentreString(row0[col], x + KEY_W/2, y + KEY_H/2);
    }

    // Draw row 1: 6-0
    for (int col = 0; col < 5; col++) {
        int x = startX + col * (KEY_W + KEY_SPACING);
        int y = startY + KEY_H + KEY_SPACING;

        display.fillRoundRect(x, y, KEY_W, KEY_H, 5, COLOR_BUTTON_BG);
        display.drawRoundRect(x, y, KEY_W, KEY_H, 5, COLOR_WHITE);
        display.setTextColor(COLOR_WHITE, COLOR_BUTTON_BG);
        display.drawCentreString(row1[col], x + KEY_W/2, y + KEY_H/2);
    }

    // Draw row 2: CLR and ENT (wider buttons)
    int bottomY = startY + 2 * (KEY_H + KEY_SPACING) + 5;
    int wideKeyW = (5 * KEY_W + 4 * KEY_SPACING - KEY_SPACING) / 2;

    // CLR button (left, red)
    display.fillRoundRect(startX, bottomY, wideKeyW, KEY_H + 5, 5, COLOR_RED);
    display.drawRoundRect(startX, bottomY, wideKeyW, KEY_H + 5, 5, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.drawCentreString("CLR", startX + wideKeyW/2, bottomY + (KEY_H+5)/2);

    // ENT button (right, green)
    int entX = startX + wideKeyW + KEY_SPACING;
    display.fillRoundRect(entX, bottomY, wideKeyW, KEY_H + 5, 5, COLOR_GREEN);
    display.drawRoundRect(entX, bottomY, wideKeyW, KEY_H + 5, 5, COLOR_WHITE);
    display.setTextColor(COLOR_BLACK, COLOR_GREEN);
    display.drawCentreString("ENT", entX + wideKeyW/2, bottomY + (KEY_H+5)/2);
}

void PINKeypad::drawPINDisplay() {
    // Title
    display.setTextSize(2);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString(promptText, SCREEN_WIDTH/2, 20);

    // PIN display area
    display.fillRect(20, 60, SCREEN_WIDTH - 40, 50, COLOR_DARK_GRAY);
    display.drawRect(20, 60, SCREEN_WIDTH - 40, 50, COLOR_WHITE);

    updateDisplay();
}

void PINKeypad::updateDisplay() {
    // Show PIN as asterisks
    String masked = "";
    for (int i = 0; i < currentPIN.length(); i++) {
        masked += "*";
    }

    display.setTextSize(3);
    display.setTextDatum(MC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_DARK_GRAY);
    display.drawCentreString(masked, SCREEN_WIDTH/2, 85);

    // Show attempts if any - positioned below keypad
    if (attempts > 0) {
        display.setTextSize(1);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        String msg = "Attempt " + String(attempts) + "/" + String(maxAttempts);
        display.fillRect(20, 230, SCREEN_WIDTH - 40, 10, COLOR_BLACK);
        display.drawCentreString(msg, SCREEN_WIDTH/2, 230);
    }
}

int PINKeypad::getKeyAt(int x, int y) {
    // Match the new 5-column layout
    int startX = (SCREEN_WIDTH - (5 * KEY_W + 4 * KEY_SPACING)) / 2;
    int startY = 70;  // Must match drawKeypad()

    Serial.println("[PINKeypad] getKeyAt x=" + String(x) + " y=" + String(y));

    // Check row 0: 1-5
    for (int col = 0; col < 5; col++) {
        int kx = startX + col * (KEY_W + KEY_SPACING);
        int ky = startY;
        if (x >= kx && x < kx + KEY_W && y >= ky && y < ky + KEY_H) {
            Serial.println("[PINKeypad] Key " + String(col + 1) + " (row 0, col " + String(col) + ")");
            return col + 1;  // 1-5
        }
    }

    // Check row 1: 6-0
    for (int col = 0; col < 5; col++) {
        int kx = startX + col * (KEY_W + KEY_SPACING);
        int ky = startY + KEY_H + KEY_SPACING;
        if (x >= kx && x < kx + KEY_W && y >= ky && y < ky + KEY_H) {
            int key = (col == 4) ? 0 : (col + 6);  // 6,7,8,9,0
            Serial.println("[PINKeypad] Key " + String(key) + " (row 1, col " + String(col) + ")");
            return key;
        }
    }

    // Check row 2: CLR and ENT (wider buttons)
    int bottomY = startY + 2 * (KEY_H + KEY_SPACING) + 5;
    int wideKeyW = (5 * KEY_W + 4 * KEY_SPACING - KEY_SPACING) / 2;

    // CLR button (left)
    if (x >= startX && x < startX + wideKeyW && y >= bottomY && y < bottomY + KEY_H + 5) {
        Serial.println("[PINKeypad] CLR pressed");
        return 10;
    }

    // ENT button (right)
    int entX = startX + wideKeyW + KEY_SPACING;
    if (x >= entX && x < entX + wideKeyW && y >= bottomY && y < bottomY + KEY_H + 5) {
        Serial.println("[PINKeypad] ENT pressed");
        return 11;
    }

    Serial.println("[PINKeypad] No key at x=" + String(x) + " y=" + String(y));
    return -1;
}
