#ifndef DISPLAYPAD_BUTTON_RENDERER_H
#define DISPLAYPAD_BUTTON_RENDERER_H

#include <Arduino.h>
#include <vector>
#include <esp_system.h>
#include "display.h"
#include "api_client.h"
#include "storage.h"

struct Button {
    int page;
    int slot;
    int x, y, w, h;
    String label;
    String iconId;
    String actionId;
    bool pressed;
    uint16_t bgColor;
    uint16_t textColor;
    uint16_t iconColor;
    bool showText;
    // Optional application icon metadata
    int applicationId;
    bool hasApplicationIcon;
    // Cache key for the application icon, may include version/hash to force
    // refresh when the icon changes.
    String applicationIconKey;
    // Runtime state: whether this Task Keypad button's application is
    // currently running on the host. Only used when the pad is in
    // task_keypad mode; in macro_keypad mode all buttons are always shown.
    bool taskAppRunning;
};

class ButtonRenderer {
public:
    ButtonRenderer();
    bool begin();

    // Load configuration
    void loadConfig(const PadConfig& config);
    void clearButtons();
    void invalidateLayout();

    // Render
    void render();
    void forceRefresh();  // Clear screen and redraw all buttons
    void renderButton(int index);
    void renderButton(const Button& btn);

    // Touch handling
    int checkTouch(int x, int y);
    void handleTouch(int x, int y);
    void releaseButton(int index);

    // Button press
    void pressButton(int index);
    bool isButtonPressed(int index);

    // Get button info
    int getButtonCount() { return buttons.size(); }
    const Button& getButton(int index) { return buttons[index]; }
    int getCurrentPage() const { return currentPage; }
    int getTotalPages() const { return totalPages; }
    bool getIsTaskKeypadMode() const { return isTaskKeypadMode; }
    std::vector<int> getPressedSlots() const;
    std::vector<int> getActiveTaskSlots() const;

    // Visual feedback
    void showPressFeedback(int index);
    void clearFeedback();

    // Taskbar
    void drawTaskbar();
    bool checkTaskbarTouch(int x, int y);  // Returns true if config gear was touched

    // Long press detection for hidden reset
    bool checkLongPress();
    void resetLongPress();

    // Reset pairing handling
    void handleResetPairing();

    // Task Keypad runtime state: control which buttons are shown based on
    // whether their associated applications are currently running.
    void clearTaskAppState();
    void setTaskAppRunning(int slot, bool running);

    // Host lock screen
    void showHostLockScreen();

private:
    std::vector<Button> buttons;
    int activeButton;
    unsigned long pressStartTime;
    static const unsigned long FEEDBACK_DURATION_MS = 100;

    // Long press tracking
    unsigned long longPressStartTime;
    bool longPressActive;
    static const unsigned long LONG_PRESS_DURATION_MS = 5000;  // 5 seconds

    // Time display configuration
    bool use24hFormat;
    bool showAmPm;
    int timezoneOffsetMinutes;

    // Paging
    int currentPage;
    int totalPages;
    int buttonsPerPage;

    // True when the current pad config mode is "task_keypad"; in this mode
    // only buttons whose taskAppRunning flag is true are rendered.
    bool isTaskKeypadMode;
    bool needsFullSurfaceClear;

    void drawButton(const Button& btn, bool highlight = false);
    void drawButtonLabel(const Button& btn);
    void drawResetButton();
    void clearButtonRegion(const Button& btn);
    void clearAllButtonRegions();
    void drawCurrentPageButtons();
    void clearPageIndicatorArea();

    void drawPageIndicators();
    int checkPageIndicatorTouch(int x, int y);
};

extern ButtonRenderer buttonRenderer;

#endif
