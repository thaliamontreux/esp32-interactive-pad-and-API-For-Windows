#ifndef DISPLAYPAD_CONTROL_PANEL_H
#define DISPLAYPAD_CONTROL_PANEL_H

#include <Arduino.h>
#include "display.h"
#include "pin_keypad.h"
#include "connection_mode.h"

enum class ControlPanelAction {
    NONE,
    WIFI_SETUP,
    BLUETOOTH_PAIRING,
    PAIRING_SETUP,
    DEVICE_DIAGNOSTICS,
    HOST_DIAGNOSTICS,
    CONFIG_REFRESH,
    RECONNECT_API,
    CONNECTION_MODE,
    RESET_PAIRING,
    RESET_WIFI,
    FACTORY_RESET,
    NEW_PROFILE,
    TIME_SETTINGS,
    EXIT
};

class ControlPanel {
public:
    ControlPanel();
    bool begin();

    // Show control panel (requires PIN entry)
    // Returns the action selected, or NONE if cancelled
    ControlPanelAction show();

    // Startup window - shows for 20 seconds at boot
    bool showStartupWindow();

    // Hidden menu access (swipe down from top or long press top bar)
    bool checkHiddenMenuGesture(int x, int y, unsigned long pressDuration);

    // Individual screens
    void showWiFiSetup();
    void showPairingSetup();
    void showDeviceDiagnostics();
    void showHostDiagnostics();
    void showTimeSettings();
    void showConnectionModeSettings();

    // Reset actions
    bool confirmReset(const String& title, const String& message);
    void doResetPairing();
    void doResetWiFi();
    void doFactoryReset();
    void doGenerateNewProfile();

private:
    void drawMainMenu();
    void drawSubscreenHeader(const String& title);
    bool handleBackButtonTouch(int x, int y);
    void drawMenuItem(int x, int y, int w, int h, const String& text, bool selected);
    int getMenuItemAt(int x, int y);
    void executeAction(ControlPanelAction action);

    static const int MENU_ITEMS = 14;
    static const char* menuLabels[MENU_ITEMS];
    static const ControlPanelAction menuActions[MENU_ITEMS];

    int selectedIndex;
    int menuScrollRow;  // index of first visible row in the 2-column grid
    bool active;
    unsigned long startupWindowStart;
};

extern ControlPanel controlPanel;

#endif
