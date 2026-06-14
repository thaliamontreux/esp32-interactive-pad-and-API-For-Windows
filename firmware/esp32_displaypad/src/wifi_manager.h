#ifndef DISPLAYPAD_WIFI_MANAGER_H
#define DISPLAYPAD_WIFI_MANAGER_H

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include "config.h"

enum class WiFiState {
    DISCONNECTED,
    CONNECTING,
    CONNECTED,
    AP_MODE,
    ERROR
};

class WiFiManager {
public:
    WiFiManager();
    bool begin();
    void loop();

    // Connection
    bool connect(const String& ssid, const String& password);
    bool reconnect();
    void disconnect();
    bool isConnected();
    WiFiState getState();

    // AP mode for setup
    bool startAP(const String& ssid = "DisplayPad-Setup");
    void stopAP();
    bool isAPMode();

    // Status
    String getIP();
    String getSSID();
    int getRSSI();

    // Web server for AP mode configuration
    void handleAPClient();

private:
    WiFiState state;
    String savedSSID;
    String savedPass;
    unsigned long lastReconnectAttempt;
    static const unsigned long RECONNECT_INTERVAL = 30000;

    // Web server for captive portal (AP mode)
    AsyncWebServer* server;
    void setupWebServer();
    void handleRoot(AsyncWebServerRequest *request);
    void handleSave(AsyncWebServerRequest *request);
};

extern WiFiManager wifiManager;

#endif
