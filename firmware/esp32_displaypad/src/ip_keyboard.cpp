#include "ip_keyboard.h"

IPKeyboard ipKeyboard;

IPKeyboard::IPKeyboard() : active(false) {}

bool IPKeyboard::begin() {
    return true;
}

bool IPKeyboard::getInput(String& outText, const String& prompt, const String& initialValue) {
    currentText = initialValue;
    promptText = prompt;
    active = true;

    display.clear();
    drawDisplay();
    drawKeyboard();

    unsigned long startTime = millis();
    const unsigned long timeout = 120000;  // 2 minute timeout

    while (active) {
        if (millis() - startTime > timeout) {
            active = false;
            return false;
        }

        int tx, ty;
        if (display.getTouch(&tx, &ty)) {
            int key = getKeyAt(tx, ty);
            if (key >= 0) {
                delay(200);  // Debounce

                if (key >= 0 && key <= 9) {
                    // Digit 0-9
                    if (currentText.length() < 15) {  // IP max length
                        currentText += String(key);
                        updateDisplay();
                    }
                } else if (key == 10) {
                    // Period (.)
                    if (currentText.length() < 15 && currentText.length() > 0) {
                        // Don't add if last char is already a period
                        if (currentText[currentText.length() - 1] != '.') {
                            currentText += ".";
                            updateDisplay();
                        }
                    }
                } else if (key == 11) {
                    // Backspace
                    if (currentText.length() > 0) {
                        currentText.remove(currentText.length() - 1);
                        updateDisplay();
                    }
                } else if (key == 12) {
                    // Enter/Done
                    if (currentText.length() > 0) {
                        outText = currentText;
                        active = false;
                        return true;
                    }
                } else if (key == 13) {
                    // Cancel
                    active = false;
                    return false;
                }
            }
        }

        delay(10);
    }

    return false;
}

void IPKeyboard::drawDisplay() {
    // Draw prompt
    display.setTextSize(1);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString(promptText, SCREEN_WIDTH/2, 5);

    // Draw text box for IP
    display.fillRect(20, 20, SCREEN_WIDTH - 40, 30, COLOR_DARK_GRAY);
    display.drawRect(20, 20, SCREEN_WIDTH - 40, 30, COLOR_WHITE);

    updateDisplay();
}

void IPKeyboard::updateDisplay() {
    // Clear text area
    display.fillRect(22, 22, SCREEN_WIDTH - 44, 26, COLOR_DARK_GRAY);

    // Draw current text
    display.setTextSize(2);
    display.setTextDatum(MC_DATUM);
    display.setTextColor(COLOR_CYAN, COLOR_DARK_GRAY);
    display.drawCentreString(currentText, SCREEN_WIDTH/2, 35);
}

void IPKeyboard::drawKeyboard() {
    // Layout: 3 rows of numbers, bottom row for controls
    // Row 0: 1 2 3
    // Row 1: 4 5 6
    // Row 2: 7 8 9
    // Row 3: . 0 <-
    // Bottom: Cancel    Enter

    const char* labels[4][3] = {
        {"1", "2", "3"},
        {"4", "5", "6"},
        {"7", "8", "9"},
        {".", "0", "<-"}
    };

    int startX = (SCREEN_WIDTH - (3 * KEY_W + 2 * KEY_SPACING)) / 2;
    int startY = 60;  // Below the IP display box

    display.setTextSize(2);
    display.setTextDatum(MC_DATUM);

    // Draw number keys (rows 0-3)
    for (int row = 0; row < 4; row++) {
        for (int col = 0; col < 3; col++) {
            int x = startX + col * (KEY_W + KEY_SPACING);
            int y = startY + row * (KEY_H + KEY_SPACING);

            // Determine color
            uint16_t bgColor = COLOR_BUTTON_BG;
            if (row == 3 && col == 0) bgColor = COLOR_BLUE;       // Period
            if (row == 3 && col == 2) bgColor = COLOR_RED;        // Backspace

            // Draw key
            display.fillRoundRect(x, y, KEY_W, KEY_H, 4, bgColor);
            display.drawRoundRect(x, y, KEY_W, KEY_H, 4, COLOR_WHITE);

            // Draw label
            display.setTextColor(COLOR_WHITE, bgColor);
            display.drawCentreString(labels[row][col], x + KEY_W/2, y + KEY_H/2);
        }
    }

    // Draw control buttons at bottom
    int bottomY = startY + 4 * (KEY_H + KEY_SPACING) + 5;

    // Cancel button (left)
    display.fillRoundRect(30, bottomY, 80, 35, 5, COLOR_RED);
    display.drawRoundRect(30, bottomY, 80, 35, 5, COLOR_WHITE);
    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.drawCentreString("CANCEL", 70, bottomY + 17);

    // Enter button (right)
    display.fillRoundRect(SCREEN_WIDTH - 110, bottomY, 80, 35, 5, COLOR_GREEN);
    display.drawRoundRect(SCREEN_WIDTH - 110, bottomY, 80, 35, 5, COLOR_WHITE);
    display.setTextColor(COLOR_BLACK, COLOR_GREEN);
    display.drawCentreString("ENTER", SCREEN_WIDTH - 70, bottomY + 17);
}

int IPKeyboard::getKeyAt(int x, int y) {
    int startX = (SCREEN_WIDTH - (3 * KEY_W + 2 * KEY_SPACING)) / 2;
    int startY = 60;

    // Check number pad area (rows 0-3, cols 0-2)
    for (int row = 0; row < 4; row++) {
        for (int col = 0; col < 3; col++) {
            int kx = startX + col * (KEY_W + KEY_SPACING);
            int ky = startY + row * (KEY_H + KEY_SPACING);

            if (x >= kx && x < kx + KEY_W && y >= ky && y < ky + KEY_H) {
                // Return key code
                if (row == 3 && col == 0) return 10;  // Period
                if (row == 3 && col == 1) return 0;   // Zero
                if (row == 3 && col == 2) return 11;  // Backspace
                return row * 3 + col + 1;  // 1-9
            }
        }
    }

    // Check control buttons
    int bottomY = startY + 4 * (KEY_H + KEY_SPACING) + 5;

    // Cancel (30, bottomY) to (110, bottomY+35)
    if (x >= 30 && x < 110 && y >= bottomY && y < bottomY + 35) {
        return 13;  // Cancel
    }

    // Enter (SCREEN_WIDTH-110, bottomY) to (SCREEN_WIDTH-30, bottomY+35)
    if (x >= SCREEN_WIDTH - 110 && x < SCREEN_WIDTH - 30 && y >= bottomY && y < bottomY + 35) {
        return 12;  // Enter
    }

    return -1;
}
