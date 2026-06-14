#include "text_keyboard.h"

TextKeyboard textKeyboard;

const char* TextKeyboard::keysLower[4] = {
    "1234567890",
    "qwertyuiop",
    "asdfghjkl",
    "zxcvbnm"
};

const char* TextKeyboard::keysUpper[4] = {
    "!@#$%^&*()",
    "QWERTYUIOP",
    "ASDFGHJKL",
    "ZXCVBNM"
};

TextKeyboard::TextKeyboard() : active(false), shiftMode(false) {}

bool TextKeyboard::begin() {
    return true;
}

bool TextKeyboard::getInput(String& outText, const String& prompt, const String& initialValue) {
    currentText = initialValue;
    promptText = prompt;
    active = true;
    shiftMode = false;

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
                delay(200);

                if (key < 256) {
                    // Character key
                    if (currentText.length() < 64) {
                        currentText += (char)key;
                        updateDisplay();
                    }
                } else if (key == 256) {
                    // Backspace
                    if (currentText.length() > 0) {
                        currentText.remove(currentText.length() - 1);
                        updateDisplay();
                    }
                } else if (key == 257) {
                    // Shift
                    shiftMode = !shiftMode;
                    drawKeyboard();
                } else if (key == 258) {
                    // Space
                    if (currentText.length() < 64) {
                        currentText += " ";
                        updateDisplay();
                    }
                } else if (key == 259) {
                    // Enter/Done
                    outText = currentText;
                    active = false;
                    return true;
                } else if (key == 260) {
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

void TextKeyboard::drawDisplay() {
    // Draw prompt
    display.setTextSize(1);
    display.setTextDatum(TC_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_BLACK);
    display.drawCentreString(promptText, SCREEN_WIDTH/2, 5);

    // Draw text box
    display.fillRect(5, 20, SCREEN_WIDTH - 10, 25, COLOR_DARK_GRAY);
    display.drawRect(5, 20, SCREEN_WIDTH - 10, 25, COLOR_WHITE);

    updateDisplay();
}

void TextKeyboard::updateDisplay() {
    // Clear text area
    display.fillRect(7, 22, SCREEN_WIDTH - 14, 21, COLOR_DARK_GRAY);

    // Draw current text
    display.setTextSize(1);
    display.setTextDatum(ML_DATUM);
    display.setTextColor(COLOR_WHITE, COLOR_DARK_GRAY);
    display.drawString(currentText, 10, 32);

    // Draw cursor
    int textWidth = display.textWidth(currentText);
    display.fillRect(12 + textWidth, 25, 2, 15, COLOR_WHITE);
}

void TextKeyboard::drawKeyboard() {
    const char** keys = shiftMode ? keysUpper : keysLower;

    int startX = (SCREEN_WIDTH - (KEY_COLS * KEY_W + (KEY_COLS - 1) * KEY_SPACING)) / 2;
    int startY = 55;

    display.setTextSize(1);
    display.setTextDatum(MC_DATUM);

    // Draw letter keys (rows 0-3)
    for (int row = 0; row < 4; row++) {
        int cols = strlen(keys[row]);
        int rowWidth = cols * KEY_W + (cols - 1) * KEY_SPACING;
        int rowStartX = (SCREEN_WIDTH - rowWidth) / 2;

        for (int col = 0; col < cols; col++) {
            int x = rowStartX + col * (KEY_W + KEY_SPACING);
            int y = startY + row * (KEY_H + KEY_SPACING);

            display.fillRoundRect(x, y, KEY_W, KEY_H, 3, COLOR_BUTTON_BG);
            display.drawRoundRect(x, y, KEY_W, KEY_H, 3, COLOR_WHITE);

            String keyStr = String(keys[row][col]);
            display.setTextColor(COLOR_WHITE, COLOR_BUTTON_BG);
            display.drawCentreString(keyStr, x + KEY_W/2, y + KEY_H/2);
        }
    }

    // Row 4: Shift, Space, Backspace
    int y4 = startY + 4 * (KEY_H + KEY_SPACING);

    // Shift button
    display.fillRoundRect(5, y4, 45, KEY_H, 3, shiftMode ? COLOR_GREEN : COLOR_BUTTON_BG);
    display.drawRoundRect(5, y4, 45, KEY_H, 3, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, shiftMode ? COLOR_GREEN : COLOR_BUTTON_BG);
    display.drawCentreString("SHFT", 27, y4 + KEY_H/2);

    // Space bar
    display.fillRoundRect(55, y4, 130, KEY_H, 3, COLOR_BUTTON_BG);
    display.drawRoundRect(55, y4, 130, KEY_H, 3, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, COLOR_BUTTON_BG);
    display.drawCentreString("SPACE", 120, y4 + KEY_H/2);

    // Backspace
    display.fillRoundRect(190, y4, 45, KEY_H, 3, COLOR_RED);
    display.drawRoundRect(190, y4, 45, KEY_H, 3, COLOR_WHITE);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.drawCentreString("<-", 212, y4 + KEY_H/2);

    // Row 5: Cancel, Done
    int y5 = startY + 5 * (KEY_H + KEY_SPACING) + 5;

    // Cancel
    display.fillRoundRect(20, y5, 80, 30, 5, COLOR_RED);
    display.drawRoundRect(20, y5, 80, 30, 5, COLOR_WHITE);
    display.setTextSize(1);
    display.setTextColor(COLOR_WHITE, COLOR_RED);
    display.drawCentreString("CANCEL", 60, y5 + 15);

    // Done
    display.fillRoundRect(140, y5, 80, 30, 5, COLOR_GREEN);
    display.drawRoundRect(140, y5, 80, 30, 5, COLOR_WHITE);
    display.setTextColor(COLOR_BLACK, COLOR_GREEN);
    display.drawCentreString("ENTER", 180, y5 + 15);
}

int TextKeyboard::getKeyAt(int x, int y) {
    const char** keys = shiftMode ? keysUpper : keysLower;

    int startY = 55;

    // Check letter keys (rows 0-3)
    for (int row = 0; row < 4; row++) {
        int cols = strlen(keys[row]);
        int rowWidth = cols * KEY_W + (cols - 1) * KEY_SPACING;
        int startX = (SCREEN_WIDTH - rowWidth) / 2;

        for (int col = 0; col < cols; col++) {
            int kx = startX + col * (KEY_W + KEY_SPACING);
            int ky = startY + row * (KEY_H + KEY_SPACING);

            if (x >= kx && x < kx + KEY_W && y >= ky && y < ky + KEY_H) {
                return keys[row][col];
            }
        }
    }

    // Row 4 buttons
    int y4 = startY + 4 * (KEY_H + KEY_SPACING);

    // Shift
    if (x >= 5 && x < 50 && y >= y4 && y < y4 + KEY_H) return 257;
    // Space
    if (x >= 55 && x < 185 && y >= y4 && y < y4 + KEY_H) return 258;
    // Backspace
    if (x >= 190 && x < 235 && y >= y4 && y < y4 + KEY_H) return 256;

    // Row 5 buttons
    int y5 = startY + 5 * (KEY_H + KEY_SPACING) + 5;

    // Cancel
    if (x >= 20 && x < 100 && y >= y5 && y < y5 + 30) return 260;
    // Done
    if (x >= 140 && x < 220 && y >= y5 && y < y5 + 30) return 259;

    return -1;
}
