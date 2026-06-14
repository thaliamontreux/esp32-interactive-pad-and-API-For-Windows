#ifndef DISPLAYPAD_DISPLAY_H
#define DISPLAYPAD_DISPLAY_H

#include <Arduino.h>
#include <TFT_eSPI.h>
#include <XPT2046_Touchscreen.h>
#include <SPI.h>
#include "config.h"

class DisplayManager {
public:
    DisplayManager();
    bool begin();
    void clear();
    void fillScreen(uint16_t color);
    void setBacklight(bool on);

    // Basic drawing
    void drawRect(int x, int y, int w, int h, uint16_t color);
    void fillRect(int x, int y, int w, int h, uint16_t color);
    void drawRoundRect(int x, int y, int w, int h, int r, uint16_t color);
    void fillRoundRect(int x, int y, int w, int h, int r, uint16_t color);
    void drawLine(int x1, int y1, int x2, int y2, uint16_t color);
    void drawCircle(int x, int y, int r, uint16_t color);
    void fillCircle(int x, int y, int r, uint16_t color);

    // Text
    void setTextColor(uint16_t fg, uint16_t bg = COLOR_BLACK);
    void setTextSize(int size);
    void setTextDatum(int datum);
    void drawString(const String& text, int x, int y);
    void drawCentreString(const String& text, int x, int y);
    int textWidth(const String& text);

    // Touch
    bool getTouch(int* x, int* y);
    bool isTouchAvailable();

    // Screen dimensions
    int width() { return SCREEN_WIDTH; }
    int height() { return SCREEN_HEIGHT; }

    // Raw TFT access for advanced use
    TFT_eSPI* getTFT() { return &tft; }

private:
    TFT_eSPI tft;
    XPT2046_Touchscreen* touchscreen;
    bool initialized;
};

extern DisplayManager display;

#endif
