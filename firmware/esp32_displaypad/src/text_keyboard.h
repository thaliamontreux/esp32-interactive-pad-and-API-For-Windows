#ifndef DISPLAYPAD_TEXT_KEYBOARD_H
#define DISPLAYPAD_TEXT_KEYBOARD_H

#include <Arduino.h>
#include "display.h"

class TextKeyboard {
public:
    TextKeyboard();
    bool begin();

    // Show keyboard and get text input
    // Returns true if user pressed Enter, false if cancelled
    bool getInput(String& outText, const String& prompt = "Enter Text", const String& initialValue = "");

private:
    void drawKeyboard();
    void drawDisplay();
    void updateDisplay();
    int getKeyAt(int x, int y);
    void shiftKeys();

    String currentText;
    String promptText;
    bool active;
    bool shiftMode;

    // Keyboard layout
    static const int KEY_W = 20;
    static const int KEY_H = 25;
    static const int KEY_SPACING = 3;
    static const int KEY_ROWS = 6;  // Row 0-3: keys, Row 4: space, Row 5: controls
    static const int KEY_COLS = 10;

    // Key definitions for each row
    static const char* keysLower[4];
    static const char* keysUpper[4];
};

extern TextKeyboard textKeyboard;

#endif
