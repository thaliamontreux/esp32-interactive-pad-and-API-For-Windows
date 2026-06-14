#ifndef DISPLAYPAD_PIN_KEYPAD_H
#define DISPLAYPAD_PIN_KEYPAD_H

#include <Arduino.h>
#include "display.h"
#include "config.h"

enum class PINResult {
    CANCELLED,
    SUCCESS,
    LOCKED,
    ERROR
};

class PINKeypad {
public:
    PINKeypad();
    bool begin();

    // Show PIN entry screen
    // Returns the entered PIN if successful
    PINResult enterPIN(String& outPIN, const String& prompt = "Enter PIN", int maxAttempts = -1);

    // Get numeric input (for pairing codes, etc.) - no validation, just returns entered digits
    bool getNumericInput(String& outInput, const String& prompt = "Enter Code", int maxDigits = 6);

    // Validate PIN against stored hash (simplified - actual validation done server-side)
    bool validatePIN(const String& pin);

    // Set new PIN
    bool setPIN(const String& newPIN);

    // Reset to default
    void resetToDefault();

    // Check if using default PIN
    bool isDefaultPIN();

private:
    void drawKeypad();
    void drawPINDisplay();
    void handleTouch();
    int getKeyAt(int x, int y);
    void updateDisplay();

    String currentPIN;
    String promptText;
    bool active;
    int attempts;
    int maxAttempts;
    unsigned long lockoutUntil;

    // Keypad layout - adjusted to fit 320x240 landscape screen
    static const int KEY_W = 55;
    static const int KEY_H = 40;
    static const int KEY_SPACING = 6;
    static const int KEY_ROWS = 4;
    static const int KEY_COLS = 3;
    static const char* keys[KEY_ROWS][KEY_COLS];
};

extern PINKeypad pinKeypad;

#endif
