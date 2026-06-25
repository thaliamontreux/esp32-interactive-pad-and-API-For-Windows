#include "api_client.h"
#include "storage.h"
#include <mbedtls/md.h>
#include <time.h>
#include <sys/time.h>

#include "button_renderer.h"
#include "display.h"

APIClient apiClient;

APIClient::APIClient()
    : serverPort(DEFAULT_API_PORT),
      lastConfigCheck(0),
      lastWSConnectAttempt(0),
      wsConnected(false) {
    // Set up WebSocket callbacks
    wsClient.onMessage([this](WebsocketsMessage message) {
        this->onWSMessage(message);
    });
    wsClient.onEvent([this](WebsocketsEvent event, String data) {
        this->onWSEvent(event, data);
    });
}

bool APIClient::begin() {
    // Load server info from storage
    serverHost = storage.getApiIP();
    if (serverHost.length() == 0) {
        serverHost = storage.getApiHost();
    }
    serverPort = storage.getApiPort();
    deviceToken = storage.getDeviceToken();
    apiUUID = storage.getApiUUID();

    return true;
}

void APIClient::loop() {
    unsigned long now = millis();

    // If WebSocket is connected, keep it serviced
    if (wsConnected) {
        wsClient.poll();
    } else if (WiFi.status() == WL_CONNECTED) {
        // WebSocket is down but WiFi is up: periodically try to reconnect
        const unsigned long RECONNECT_INTERVAL_MS = 15000;  // 15s between attempts
        if (now - lastWSConnectAttempt > RECONNECT_INTERVAL_MS) {
            lastWSConnectAttempt = now;
            Serial.println("[API] WebSocket not connected - attempting reconnect...");
            connectWebSocket();
        }
    }

    // Periodic config check as a fallback if we cannot keep a WebSocket
    if (!wsConnected && WiFi.status() == WL_CONNECTED) {
        if (now - lastConfigCheck > CONFIG_CHECK_INTERVAL_MS) {
            lastConfigCheck = now;
            uint32_t version;
            bool updateRequired;
            checkConfigVersion(version, updateRequired);
        }
    }
}

void APIClient::setServer(const String& host, uint16_t port) {
    serverHost = host;
    serverPort = port;
}

void APIClient::setDeviceToken(const String& token) {
    deviceToken = token;
}

APIStatus APIClient::checkConfigVersion(uint32_t& version, bool& updateRequired) {
    String url = "http://" + serverHost + ":" + serverPort + "/api/v1/pads/" +
                 storage.getPadUUID() + "/config/version";

    HTTPClient http;
    http.begin(url);
    addAuthHeaders(http);

    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
        String responseBody = http.getString();
        JsonDocument response;
        deserializeJson(response, responseBody);

        version = response["config_version"];
        updateRequired = response["update_required"];
        http.end();
        return APIStatus::OK;
    }

    http.end();
    if (httpCode == 401) {
        Serial.println("[API] 401 Unauthorized - authentication failed");
        return APIStatus::AUTH_ERROR;
    }
    return APIStatus::HTTP_ERROR;
}

APIStatus APIClient::getConfig(PadConfig& config) {
    String url = "http://" + serverHost + ":" + serverPort + "/api/v1/pads/" +
                 storage.getPadUUID() + "/config";

    HTTPClient http;
    http.begin(url);
    addAuthHeaders(http);

    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
        String responseBody = http.getString();
        JsonDocument response;
        deserializeJson(response, responseBody);

        config.padId = response["pad_id"].as<String>();
        config.name = response["name"].as<String>();
        config.mode = response["pad_mode"].as<String>();
        config.buttonCount = response["button_count"];  // per page
        config.pageCount = response["page_count"] | 1;
        config.configVersion = response["config_version"];
        config.columns = response["layout"]["columns"];
        config.rows = response["layout"]["rows"];

        // Time configuration for top bar
        JsonObject timeCfg = response["time"].as<JsonObject>();
        if (!timeCfg.isNull()) {
            config.use24h = timeCfg["use_24h"] | false;
            config.showAmPm = timeCfg["show_am_pm"] | true;
            config.timezoneOffsetMinutes = timeCfg["timezone_offset_minutes"] | 0;
        } else {
            config.use24h = false;
            config.showAmPm = true;
            config.timezoneOffsetMinutes = 0;
        }

        config.buttons.clear();
        JsonArray buttons = response["buttons"];
        for (JsonObject btn : buttons) {
            ButtonConfig bc;
            bc.page = btn["page"] | 1;
            bc.slot = btn["slot"];
            bc.x = btn["x"];
            bc.y = btn["y"];
            bc.w = btn["w"];
            bc.h = btn["h"];
            bc.label = btn["label"].as<String>();
            bc.iconId = btn["icon_id"].as<String>();
            bc.actionId = btn["action_id"].as<String>();
            // Optional per-button colors as hex strings (e.g. "#RRGGBB").
            bc.bgColorHex = btn["bg_color"].as<String>();
            bc.iconColorHex = btn["icon_color"].as<String>();
            bc.textColorHex = btn["text_color"].as<String>();
            bc.showText = btn["show_text"] | true;
            // Application icon metadata
            bc.applicationId = btn["application_id"] | 0;
            bc.hasApplicationIcon = btn["has_application_icon"] | false;
            bc.applicationIconVersion = btn["application_icon_version"].as<String>();
            config.buttons.push_back(bc);
        }

        http.end();
        return APIStatus::OK;
    }

    http.end();
    if (httpCode == 401) {
        Serial.println("[API] 401 Unauthorized - authentication failed");
        return APIStatus::AUTH_ERROR;
    }
    return APIStatus::HTTP_ERROR;
}

APIStatus APIClient::confirmConfigApplied(uint32_t version) {
    String url = "http://" + serverHost + ":" + serverPort + "/api/v1/pads/" +
                 storage.getPadUUID() + "/config/applied";

    HTTPClient http;
    http.begin(url);
    addAuthHeaders(http);
    http.addHeader("Content-Type", "application/json");

    JsonDocument request;
    request["config_version"] = version;
    request["status"] = "applied";

    String requestBody;
    serializeJson(request, requestBody);

    int httpCode = http.POST(requestBody);
    http.end();

    return (httpCode == HTTP_CODE_OK) ? APIStatus::OK : APIStatus::HTTP_ERROR;
}

APIStatus APIClient::getHostSessionState(bool& locked) {
    String url = "http://" + serverHost + ":" + serverPort + "/api/v1/system/host_session_state";

    HTTPClient http;
    http.begin(url);
    addAuthHeaders(http);

    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
        String responseBody = http.getString();
        JsonDocument response;
        DeserializationError error = deserializeJson(response, responseBody);
        http.end();
        if (error) {
            return APIStatus::HTTP_ERROR;
        }
        locked = response["locked"] | false;
        return APIStatus::OK;
    }

    http.end();
    if (httpCode == 401) {
        Serial.println("[API] 401 Unauthorized - authentication failed");
        return APIStatus::AUTH_ERROR;
    }
    return APIStatus::HTTP_ERROR;
}

APIStatus APIClient::sendButtonPress(int slot, const String& pressType) {
    String url = "http://" + serverHost + ":" + serverPort + "/api/v1/pads/" +
                 storage.getPadUUID() + "/press";

    HTTPClient http;
    http.begin(url);
    addAuthHeaders(http);
    http.addHeader("Content-Type", "application/json");

    JsonDocument request;
    request["slot"] = slot;
    request["press_type"] = pressType;

    String requestBody;
    serializeJson(request, requestBody);

    int httpCode = http.POST(requestBody);
    http.end();

    return (httpCode == HTTP_CODE_OK) ? APIStatus::OK : APIStatus::HTTP_ERROR;
}

bool APIClient::connectWebSocket() {
    String wsUrl = "ws://" + serverHost + ":" + serverPort + "/api/v1/pads/" + storage.getPadUUID() + "/ws";

    Serial.println("Connecting WebSocket to: " + wsUrl);

    bool connected = wsClient.connect(wsUrl.c_str());
    if (connected) {
        wsConnected = true;
        Serial.println("WebSocket connection initiated");
    } else {
        Serial.println("WebSocket connection failed");
    }

    return connected;
}

void APIClient::disconnectWebSocket() {
    wsClient.close();
    wsConnected = false;
}

bool APIClient::isWebSocketConnected() {
    return wsConnected && wsClient.available();
}

void APIClient::addAuthHeaders(HTTPClient& http) {
    // Simple auth - just device token in header
    http.addHeader("X-Pad-UUID", storage.getPadUUID());
    http.addHeader("X-Device-Token", storage.getDeviceToken());
}

void APIClient::onWSMessage(WebsocketsMessage message) {
    String data = message.data();
    Serial.println("WebSocket message: " + data);

    // Parse JSON message
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, data);

    if (!error) {
        String msgType = doc["type"].as<String>();

        if (msgType == "task_app_state") {
            extern bool g_hostDisplayLocked;
            // While the host display is locked we keep showing the lock
            // screen image and ignore task_app_state updates so the keypad
            // UI does not change underneath the lock screen.
            if (g_hostDisplayLocked) {
                return;
            }
            // Real-time Task Keypad update: server is telling us which
            // application-launch buttons are currently backed by running
            // processes on the host. We update the ButtonRenderer's
            // taskAppRunning flags so that only those buttons are drawn in
            // Task Keypad mode.
            JsonArray arr = doc["buttons"].as<JsonArray>();

            extern ButtonRenderer buttonRenderer;
            buttonRenderer.clearTaskAppState();

            for (JsonObject obj : arr) {
                int slot = obj["slot"] | 0;
                bool running = obj["running"] | false;
                if (slot > 0 && running) {
                    buttonRenderer.setTaskAppRunning(slot, true);
                }
            }

            // Mark buttons dirty so the main loop knows to re-render.
            extern bool buttonsDirty;
            buttonsDirty = true;
            return;
        }

        if (msgType == "time") {
            long epoch = doc["epoch"] | 0;
            if (epoch > 0) {
                struct timeval tv;
                tv.tv_sec = epoch;
                tv.tv_usec = 0;
                settimeofday(&tv, nullptr);
            }
            return;
        }

        if (msgType == "host_display_state") {
            String state = doc["state"].as<String>();
            bool locked = (state == "locked");

            extern DisplayManager display;
            extern ButtonRenderer buttonRenderer;
            extern bool g_hostDisplayLocked;

            // Ensure backlight is on so the lock screen image is visible.
            display.setBacklight(true);

            // Remember the host lock state so that the main render loop can
            // suppress normal button drawing while locked.
            g_hostDisplayLocked = locked;

            if (locked) {
                Serial.println("[POWER] WiFi: host_display_state=locked; showing lock screen");
                buttonRenderer.showHostLockScreen();
            } else {
                // On unlock, mark buttons dirty so the normal keypad UI is
                // fully re-rendered.
                Serial.println("[POWER] WiFi: host_display_state=unlocked; refreshing buttons");
                extern bool buttonsDirty;
                buttonsDirty = true;
            }
            return;
        }

        if (configUpdateCallback && msgType == "config_update_pending") {
            configUpdateCallback(msgType, doc);
        }
    }
}

void APIClient::onWSEvent(WebsocketsEvent event, String data) {
    switch (event) {
        case WebsocketsEvent::ConnectionOpened:
            wsConnected = true;
            Serial.println("WebSocket connected");
            break;

        case WebsocketsEvent::ConnectionClosed:
            wsConnected = false;
            Serial.println("WebSocket disconnected");
            break;

        case WebsocketsEvent::GotPing:
            // Auto-handled by library
            break;

        case WebsocketsEvent::GotPong:
            // Auto-handled by library
            break;

        default:
            break;
    }
}

void APIClient::startLogSession(const String& sessionUUID, const String& bootReason, const String& fwVersion) {
    if (!isWebSocketConnected()) {
        return;
    }

    JsonDocument doc;
    doc["type"] = "log_session_start";
    doc["session_uuid"] = sessionUUID;
    if (bootReason.length() > 0) {
        doc["boot_reason"] = bootReason;
    }
    if (fwVersion.length() > 0) {
        doc["fw_version"] = fwVersion;
    }

    String body;
    serializeJson(doc, body);
    wsClient.send(body);
}

void APIClient::sendPadStatus(const String& payload) {
    if (!isWebSocketConnected()) {
        return;
    }
    wsClient.send(payload);
}

void APIClient::sendLogLine(const String& sessionUUID, uint32_t seq, const String& message, const String& level) {
    if (!isWebSocketConnected()) {
        return;
    }

    JsonDocument doc;
    doc["type"] = "log";
    doc["session_uuid"] = sessionUUID;
    doc["seq"] = seq;
    doc["level"] = level;
    doc["message"] = message;

    String body;
    serializeJson(doc, body);
    wsClient.send(body);
}
