#ifndef DISPLAYPAD_IP_KEYBOARD_H
#define DISPLAYPAD_IP_KEYBOARD_H

#include <Arduino.h>
#include "display.h"

class IPKeyboard {
public:
    IPKeyboard();
    bool begin();

    // Show numeric keyboard for IP entry
    // Returns true if user pressed Enter, false if cancelled
    bool getInput(String& outText, const String& prompt = "Enter IP", const String& initialValue = "");

private:
    void drawKeyboard();
    void drawDisplay();
    void updateDisplay();
    int getKeyAt(int x, int y);

    String currentText;
    String promptText;
    bool active;

    // Key dimensions - optimized for 320x240 landscape
    static const int KEY_W = 55;
    static const int KEY_H = 35;
    static const int KEY_SPACING = 6;
};

extern IPKeyboard ipKeyboard;

#endif
