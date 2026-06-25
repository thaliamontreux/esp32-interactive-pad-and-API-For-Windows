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
    // Enforce an exact 4-digit PIN on the device. There are two cases:
    //  1) Default PIN in use (no stored hash): accept DEFAULT_PIN only.
    //  2) Custom PIN set (stored hash present): accept only if the hash
    //     of the entered PIN matches the stored hash.

    if (pin.length() != PIN_MAX_LENGTH) {
        return false;
    }

    // All digits check
    for (int i = 0; i < pin.length(); i++) {
        if (!isdigit(pin[i])) return false;
    }

    String storedHash = storage.getPINHash();
    if (storedHash.length() == 0) {
        // No custom PIN set; use firmware default
        return pin == DEFAULT_PIN;
    }

    // Compare SHA-256 hash of entered PIN with stored hash
    uint8_t hash[32];
    mbedtls_sha256((const uint8_t*)pin.c_str(), pin.length(), hash, 0);

    char hashStr[65];
    for (int i = 0; i < 32; i++) {
        sprintf(&hashStr[i * 2], "%02X", hash[i]);
    }
    hashStr[64] = '\0';

    return storedHash.equalsIgnoreCase(hashStr);
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
    int startY = 90;  // Below compact PIN display

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
    display.drawCentreString(promptText, SCREEN_WIDTH/2, 18);

    // PIN display area (compact band for four indicator dots)
    int boxX = 40;
    int boxY = 40;
    int boxW = SCREEN_WIDTH - 80;
    int boxH = 30;

    display.fillRect(boxX, boxY, boxW, boxH, COLOR_DARK_GRAY);
    display.drawRect(boxX, boxY, boxW, boxH, COLOR_WHITE);

    updateDisplay();
}

void PINKeypad::updateDisplay() {
    // Draw four status dots representing each PIN digit. Empty = white,
    // entered = green.
    int boxX = 40;
    int boxY = 40;
    int boxW = SCREEN_WIDTH - 80;
    int boxH = 30;

    // Clear inside the PIN box
    display.fillRect(boxX + 1, boxY + 1, boxW - 2, boxH - 2, COLOR_DARK_GRAY);

    const int totalDots = 4;
    int radius = 5;
    int centerY = boxY + boxH / 2;

    int totalWidth = totalDots * (radius * 2) + (totalDots - 1) * 12;
    int startX = SCREEN_WIDTH / 2 - totalWidth / 2 + radius;

    int filled = currentPIN.length();
    if (filled > totalDots) filled = totalDots;

    for (int i = 0; i < totalDots; ++i) {
        int cx = startX + i * (2 * radius + 12);
        uint16_t color = (i < filled) ? COLOR_GREEN : COLOR_WHITE;
        display.fillCircle(cx, centerY, radius, color);
    }

    // Show attempts if any - positioned below keypad
    if (attempts > 0) {
        display.setTextSize(1);
        display.setTextDatum(TC_DATUM);
        display.setTextColor(COLOR_RED, COLOR_BLACK);
        String msg = "Attempt " + String(attempts) + "/" + String(maxAttempts);
        display.fillRect(20, 220, SCREEN_WIDTH - 40, 12, COLOR_BLACK);
        display.drawCentreString(msg, SCREEN_WIDTH/2, 222);
    }
}

int PINKeypad::getKeyAt(int x, int y) {
    // Match the new 5-column layout
    int startX = (SCREEN_WIDTH - (5 * KEY_W + 4 * KEY_SPACING)) / 2;
    int startY = 90;  // Must match drawKeypad()

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
