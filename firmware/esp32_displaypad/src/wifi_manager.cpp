#include "wifi_manager.h"
#include "storage.h"
#include <time.h>

WiFiManager wifiManager;

WiFiManager::WiFiManager() : state(WiFiState::DISCONNECTED), lastReconnectAttempt(0), server(nullptr) {}

bool WiFiManager::begin() {
    WiFi.mode(WIFI_STA);

    // Load saved credentials
    savedSSID = storage.getWiFiSSID();
    savedPass = storage.getWiFiPass();

    if (savedSSID.length() > 0) {
        return reconnect();
    }

    return false;
}

void WiFiManager::loop() {
    // Check connection status
    if (state == WiFiState::CONNECTED && WiFi.status() != WL_CONNECTED) {
        state = WiFiState::DISCONNECTED;
    }

    // Auto-reconnect if disconnected (but not in AP mode)
    if (state == WiFiState::DISCONNECTED && savedSSID.length() > 0 && !isAPMode()) {
        unsigned long now = millis();
        if (now - lastReconnectAttempt > RECONNECT_INTERVAL) {
            lastReconnectAttempt = now;
            reconnect();
        }
    }

    // ESPAsyncWebServer is async - no handleClient() needed
}

bool WiFiManager::connect(const String& ssid, const String& password) {
    savedSSID = ssid;
    savedPass = password;

    state = WiFiState::CONNECTING;

    // Use DHCP-provided DNS so that NTP (`pool.ntp.org`) and other lookups
    // respect the network's configuration instead of forcing 8.8.8.8, which
    // can be blocked on some networks and cause connection instability.
    WiFi.begin(ssid.c_str(), password.c_str());

    // Wait up to 20 seconds for connection
    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
        delay(500);
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        state = WiFiState::CONNECTED;

        // Configure NTP for time sync using pool.ntp.org as the primary
        // source.
        configTime(0, 0, "pool.ntp.org");
        Serial.println("[Time][WiFi] Connected, NTP configured (pool.ntp.org)");

        // Wait briefly for time to sync (optional - time() will return 0 until synced)
        delay(100);

        // Save credentials
        storage.setWiFiSSID(ssid);
        storage.setWiFiPass(password);
        return true;
    }

    state = WiFiState::ERROR;
    return false;
}

bool WiFiManager::reconnect() {
    if (savedSSID.length() == 0) return false;
    return connect(savedSSID, savedPass);
}

void WiFiManager::disconnect() {
    WiFi.disconnect();
    state = WiFiState::DISCONNECTED;
}

bool WiFiManager::isConnected() {
    return state == WiFiState::CONNECTED && WiFi.status() == WL_CONNECTED;
}

WiFiState WiFiManager::getState() {
    return state;
}

bool WiFiManager::startAP(const String& ssid) {
    WiFi.mode(WIFI_AP);
    WiFi.softAP(ssid.c_str());
    state = WiFiState::AP_MODE;

    setupWebServer();
    return true;
}

void WiFiManager::stopAP() {
    if (server) {
        // ESPAsyncWebServer doesn't have stop(), just delete it
        delete server;
        server = nullptr;
    }
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    state = WiFiState::DISCONNECTED;
}

bool WiFiManager::isAPMode() {
    return WiFi.getMode() == WIFI_AP || state == WiFiState::AP_MODE;
}

String WiFiManager::getIP() {
    if (isAPMode()) {
        return WiFi.softAPIP().toString();
    }
    return WiFi.localIP().toString();
}

String WiFiManager::getSSID() {
    return savedSSID;
}

int WiFiManager::getRSSI() {
    return WiFi.RSSI();
}

void WiFiManager::handleAPClient() {
    // ESPAsyncWebServer is async - no handleClient() needed
}

void WiFiManager::setupWebServer() {
    server = new AsyncWebServer(80);

    // Root handler - WiFi setup form
    server->on("/", HTTP_GET, [this](AsyncWebServerRequest *request) {
        this->handleRoot(request);
    });

    // Save handler - POST form submission
    server->on("/save", HTTP_POST, [this](AsyncWebServerRequest *request) {
        this->handleSave(request);
    });

    server->begin();
}

void WiFiManager::handleRoot(AsyncWebServerRequest *request) {
    String html = R"(
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DisplayPad WiFi Setup</title>
    <style>
        body { font-family: Arial; padding: 20px; max-width: 400px; margin: 0 auto; }
        h1 { color: #0078d4; }
        input { width: 100%; padding: 10px; margin: 10px 0; box-sizing: border-box; }
        button { width: 100%; padding: 15px; background: #0078d4; color: white; border: none; cursor: pointer; }
        button:hover { background: #005a9e; }
    </style>
</head>
<body>
    <h1>DisplayPad WiFi Setup</h1>
    <form action="/save" method="post">
        <input type="text" name="ssid" placeholder="WiFi SSID" required>
        <input type="password" name="pass" placeholder="WiFi Password" required>
        <button type="submit">Connect</button>
    </form>
</body>
</html>
)";
    request->send(200, "text/html", html);
}

void WiFiManager::handleSave(AsyncWebServerRequest *request) {
    String ssid = "";
    String pass = "";

    // Get form parameters
    if (request->hasParam("ssid", true)) {
        ssid = request->getParam("ssid", true)->value();
    }
    if (request->hasParam("pass", true)) {
        pass = request->getParam("pass", true)->value();
    }

    String html = R"(
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>DisplayPad</title>
    <style>
        body { font-family: Arial; padding: 20px; max-width: 400px; margin: 0 auto; text-align: center; }
        h1 { color: #0078d4; }
    </style>
</head>
<body>
    <h1>Connecting...</h1>
    <p>The DisplayPad will now attempt to connect to your WiFi network.</p>
    <p>If successful, the setup AP will close.</p>
</body>
</html>
)";
    request->send(200, "text/html", html);

    // Try to connect
    delay(1000);
    if (connect(ssid, pass)) {
        stopAP();
    }
}
