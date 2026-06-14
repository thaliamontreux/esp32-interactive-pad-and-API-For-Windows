#ifndef DISPLAYPAD_STORAGE_H
#define DISPLAYPAD_STORAGE_H

#include <Arduino.h>
#include <Preferences.h>
#include "config.h"

class SecureStorage {
public:
    SecureStorage();
    bool begin();
    void end();

    // Pad identity
    bool setPadUUID(const String& uuid);
    String getPadUUID();
    bool setPadSecret(const String& secret);
    String getPadSecret();

    // API settings
    bool setApiUUID(const String& uuid);
    String getApiUUID();
    bool setApiHost(const String& host);
    String getApiHost();
    bool setApiIP(const String& ip);
    String getApiIP();
    bool setApiPort(uint16_t port);
    uint16_t getApiPort();

    // Device token
    bool setDeviceToken(const String& token);
    String getDeviceToken();

    // Config version
    bool setConfigVersion(uint32_t version);
    uint32_t getConfigVersion();

    // PIN
    bool setPINHash(const String& hash);
    String getPINHash();

    // WiFi credentials
    bool setWiFiSSID(const String& ssid);
    String getWiFiSSID();
    bool setWiFiPass(const String& pass);
    String getWiFiPass();

    // Pairing status
    bool setPaired(bool paired);
    bool isPaired();

    // Diagnostics: how many times last-known API IP fallback has failed and we
    // had to fall back to full network discovery.
    bool setLastIpFailureCount(uint32_t count);
    uint32_t getLastIpFailureCount();

    // Factory reset
    bool factoryReset();

    // Generate new pad profile
    bool generateNewProfile();

private:
    Preferences prefs;
    bool initialized;
};

extern SecureStorage storage;

#endif
