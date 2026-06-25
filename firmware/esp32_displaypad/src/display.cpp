#include "display.h"

DisplayManager display;

DisplayManager::DisplayManager() : initialized(false), touchscreen(nullptr) {}

bool DisplayManager::begin() {
    Serial.println("[Display] Initializing...");

    // Initialize backlight with PWM for CYD boards
    // Some CYD boards need PWM control on GPIO 21
    #if defined(TFT_BL)
    Serial.println("[Display] Setting up PWM backlight on pin " + String(TFT_BL));

    // Setup LEDC for PWM backlight control (ESP32 Arduino core 2.0.x API)
    const int kBacklightChannel = 0;
    ledcSetup(kBacklightChannel, 5000, 8);   // Channel, 5kHz, 8-bit resolution
    ledcAttachPin(TFT_BL, kBacklightChannel);
    ledcWrite(kBacklightChannel, 255);       // Full brightness

    delay(100);
    Serial.println("[Display] Backlight PWM set to full brightness");
    #else
    Serial.println("[Display] TFT_BL not defined");
    #endif

    // Some boards need manual SPI pin setup
    #if defined(USE_HSPI_PORT)
    Serial.println("[Display] Using HSPI port");
    #endif

    Serial.println("[Display] Calling tft.init()...");
    tft.init();
    Serial.println("[Display] tft.init() complete");

    tft.setRotation(TFT_ROTATION);  // Landscape mode (rotation 1)
    Serial.println("[Display] Display set to landscape mode");

    // Initialize XPT2046 touchscreen on separate VSPI bus
    Serial.println("[Display] Initializing XPT2046 touchscreen...");
    // Create touchscreen with CS pin and optional IRQ
    touchscreen = new XPT2046_Touchscreen(TOUCH_CS, TOUCH_IRQ);

    // Initialize with VSPI pins (MISO=39, MOSI=32, SCLK=25)
    // Note: XPT2046_Touchscreen library uses SPI library internally
    SPIClass* vspi = new SPIClass(VSPI);
    vspi->begin(25, 39, 32, 33);  // SCLK, MISO, MOSI, CS

    if (touchscreen->begin(*vspi)) {
        Serial.println("[Display] XPT2046 touchscreen initialized successfully");
        touchscreen->setRotation(1);  // Match display rotation for landscape
    } else {
        Serial.println("[Display] XPT2046 touchscreen init failed");
    }

    // Startup test pattern (color cycling + "Display OK" screen) has been
    // disabled to avoid flashing colors on boot. If needed for diagnostics,
    // this block can be re-enabled or moved behind a debug flag.

    // Initialize touch IRQ pin if defined
    #if defined(TOUCH_IRQ)
    Serial.println("[Display] Setting up touch IRQ on pin " + String(TOUCH_IRQ));
    // GPIO 36 is input-only (RTC GPIO), no internal pullup available
    pinMode(TOUCH_IRQ, INPUT);
    #endif

    // Touch test - wait briefly and check for touch
    Serial.println("[Display] Testing touch (touch screen to continue)...");
    unsigned long touchTestStart = millis();
    bool touchDetected = false;
    while (millis() - touchTestStart < 3000) {  // 3 second window
        if (touchscreen && touchscreen->touched()) {
            TS_Point p = touchscreen->getPoint();
            Serial.println("[Display] Touch detected at x=" + String(p.x) + " y=" + String(p.y));
            touchDetected = true;
            break;
        }
        delay(50);
    }
    if (!touchDetected) {
        Serial.println("[Display] No touch detected during test");
    }

    initialized = true;
    return true;
}

void DisplayManager::setBacklight(bool on) {
    #if defined(TFT_BL)
    digitalWrite(TFT_BL, on ? HIGH : LOW);
    #endif
}

void DisplayManager::clear() {
    tft.fillScreen(COLOR_BLACK);
}

void DisplayManager::fillScreen(uint16_t color) {
    tft.fillScreen(color);
}

void DisplayManager::drawRect(int x, int y, int w, int h, uint16_t color) {
    tft.drawRect(x, y, w, h, color);
}

void DisplayManager::fillRect(int x, int y, int w, int h, uint16_t color) {
    tft.fillRect(x, y, w, h, color);
}

void DisplayManager::drawRoundRect(int x, int y, int w, int h, int r, uint16_t color) {
    tft.drawRoundRect(x, y, w, h, r, color);
}

void DisplayManager::fillRoundRect(int x, int y, int w, int h, int r, uint16_t color) {
    tft.fillRoundRect(x, y, w, h, r, color);
}

void DisplayManager::drawLine(int x1, int y1, int x2, int y2, uint16_t color) {
    tft.drawLine(x1, y1, x2, y2, color);
}

void DisplayManager::drawCircle(int x, int y, int r, uint16_t color) {
    tft.drawCircle(x, y, r, color);
}

void DisplayManager::fillCircle(int x, int y, int r, uint16_t color) {
    tft.fillCircle(x, y, r, color);
}

void DisplayManager::setTextColor(uint16_t fg, uint16_t bg) {
    tft.setTextColor(fg, bg);
}

void DisplayManager::setTextSize(int size) {
    tft.setTextSize(size);
}

void DisplayManager::setTextDatum(int datum) {
    tft.setTextDatum(datum);
}

void DisplayManager::drawString(const String& text, int x, int y) {
    tft.drawString(text, x, y);
}

void DisplayManager::drawCentreString(const String& text, int x, int y) {
    tft.drawCentreString(text, x, y, 1);
}

int DisplayManager::textWidth(const String& text) {
    return tft.textWidth(text);
}

bool DisplayManager::getTouch(int* x, int* y) {
    if (!touchscreen || !touchscreen->touched()) {
        return false;
    }

    TS_Point p = touchscreen->getPoint();

    // XPT2046 returns raw ADC values (0-4095)
    // Map to screen coordinates based on rotation
    // Calibration values for ESP32-2432S028R
    int screenX = map(p.x, 300, 3800, 0, SCREEN_WIDTH);
    int screenY = map(p.y, 300, 3800, 0, SCREEN_HEIGHT);

    // Clamp to screen bounds
    screenX = constrain(screenX, 0, SCREEN_WIDTH - 1);
    screenY = constrain(screenY, 0, SCREEN_HEIGHT - 1);

    if (x) *x = screenX;
    if (y) *y = screenY;

    return true;
}

bool DisplayManager::isTouchAvailable() {
    return touchscreen != nullptr;
}
