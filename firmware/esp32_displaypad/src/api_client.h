#ifndef DISPLAYPAD_API_CLIENT_H
#define DISPLAYPAD_API_CLIENT_H

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "config.h"

using namespace websockets;

enum class APIStatus {
    OK,
    DISCONNECTED,
    AUTH_ERROR,
    HTTP_ERROR,
    NETWORK_ERROR
};

struct ButtonConfig {
    int page;
    int slot;      // slot index within the page
    int x, y, w, h;
    String label;
    String iconId;
    String actionId;
    // Optional per-button colors as hex strings from the server (e.g. "#RRGGBB").
    String bgColorHex;
    String iconColorHex;
    String textColorHex;
    bool showText;
    // Optional application linkage for application icons
    int applicationId;
    bool hasApplicationIcon;
    // Optional version/hash for the application icon so we can invalidate
    // cached PNGs when the icon changes.
    String applicationIconVersion;
};

struct PadConfig {
    String padId;
    String name;
    String mode;
    int buttonCount;   // buttons per page
    int pageCount;     // total number of pages
    uint32_t configVersion;
    int columns;
    int rows;
    bool use24h;
    bool showAmPm;
    int timezoneOffsetMinutes;  // minutes offset from UTC for server timezone
    std::vector<ButtonConfig> buttons;
};

class APIClient {
public:
    APIClient();
    bool begin();
    void loop();

    // Config
    APIStatus checkConfigVersion(uint32_t& version, bool& updateRequired);
    APIStatus getConfig(PadConfig& config);
    APIStatus confirmConfigApplied(uint32_t version);

    // Button press
    APIStatus sendButtonPress(int slot, const String& pressType = "tap");

    // WebSocket
    bool connectWebSocket();
    void disconnectWebSocket();
    bool isWebSocketConnected();

    // Server info
    void setServer(const String& host, uint16_t port);
    void setDeviceToken(const String& token);

    // Callbacks
    typedef std::function<void(const String& type, JsonDocument& data)> ConfigUpdateCallback;
    void onConfigUpdate(ConfigUpdateCallback cb) { configUpdateCallback = cb; }

    // Logging helpers: stream console-style logs from the ESP32 to the
    // DisplayPad API over the existing WebSocket so they can be stored and
    // viewed per-device in the GUI.
    void startLogSession(const String& sessionUUID, const String& bootReason, const String& fwVersion);
    void sendLogLine(const String& sessionUUID, uint32_t seq, const String& message, const String& level = "INFO");

private:
    String serverHost;
    uint16_t serverPort;
    String deviceToken;
    String apiUUID;
    unsigned long lastConfigCheck;
    unsigned long lastWSConnectAttempt;
    bool wsConnected;

    WebsocketsClient wsClient;
    ConfigUpdateCallback configUpdateCallback;

    // WebSocket events
    void onWSMessage(WebsocketsMessage message);
    void onWSEvent(WebsocketsEvent event, String data);

    // HTTP helpers
    APIStatus doPost(const String& endpoint, JsonDocument& request, JsonDocument& response);
    APIStatus doGetWithAuth(const String& endpoint, JsonDocument& response);

    // Headers
    void addAuthHeaders(HTTPClient& http);
};

extern APIClient apiClient;

#endif
