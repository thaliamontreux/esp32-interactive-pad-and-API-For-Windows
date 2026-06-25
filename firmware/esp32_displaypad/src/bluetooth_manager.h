#ifndef DISPLAYPAD_BLUETOOTH_MANAGER_H
#define DISPLAYPAD_BLUETOOTH_MANAGER_H

#include <Arduino.h>
#include <vector>

class BluetoothManager {
public:
    BluetoothManager();

    // Initialize the Bluetooth radio and start the SPP service.
    void begin();

    // Periodic processing hook; non-blocking.
    void loop();

    // True when a host is connected over Bluetooth SPP.
    bool isConnected() const;

    // Convenience helper to send a single JSON line terminated by \n.
    bool sendJsonLine(const String& line);

    // Retrieve and clear any pending JSON lines that were received from the
    // host. Each line is a raw JSON string without the trailing newline.
    void drainPendingLines(std::vector<String>& out);

    // Millis timestamps of last BLE RX/TX activity. Used for UI indicators
    // in Bluetooth mode.
    unsigned long getLastRxActivityMs() const;
    unsigned long getLastTxActivityMs() const;

    // Begin a new pairing session by generating a random 6-digit PIN and
    // applying it to the Bluetooth stack. Returns the PIN so the UI can
    // display it to the user.
    String startPairingSession();

    // Get the currently active pairing PIN (most recently generated).
    String getCurrentPin() const;

    // Remove all stored BLE bonds. Used when the user explicitly starts a new
    // pairing session so a stale/mismatched bond on the host (e.g. after a
    // firmware reflash) cannot block fresh pairing.
    void clearBonds();

private:
    bool started;
    bool lastConnected;
    String lineBuffer;
    std::vector<String> pendingLines;
    String currentPin;
};

extern BluetoothManager btManager;

#endif
