#include "icon_cache.h"

#include <LittleFS.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "storage.h"
#include "config.h"

#define ICON_FS LittleFS

IconCache iconCache;

bool IconCache::begin() {
    if (!ICON_FS.begin(true)) {
        return false;
    }
    // On each boot, clear any previously cached icon PNGs so that
    // application icons are always reloaded from the API after a reboot.
    // We still cache icons within a single boot via ensureIcon(), but we
    // do not persist them across restarts.
    File root = ICON_FS.open("/");
    if (root) {
        File file = root.openNextFile();
        while (file) {
            String name = file.name();
            if (name.startsWith("/icon_") && name.endsWith(".png")) {
                ICON_FS.remove(name);
            }
            file = root.openNextFile();
        }
        root.close();
    }
    return true;
}

String IconCache::getIconPath(const String& iconId) {
    String safe = iconId;
    safe.replace("/", "_");
    safe.replace("\\", "_");
    return String("/icon_") + safe + ".png";
}

bool IconCache::hasIcon(const String& iconId) {
    if (iconId.length() == 0) {
        return false;
    }
    String path = getIconPath(iconId);
    return ICON_FS.exists(path);
}

bool IconCache::ensureIcon(const String& iconId) {
    if (iconId.length() == 0) {
        return false;
    }

    String path = getIconPath(iconId);
    if (ICON_FS.exists(path)) {
        Serial.println("[IconCache] Cache hit for iconId='" + iconId + "' path='" + path + "'");
        return true;
    }

    String host = storage.getApiHost();
    uint16_t port = storage.getApiPort();
    if (host.length() == 0 || port == 0) {
        return false;
    }

    if (!WiFi.isConnected()) {
        Serial.println("[IconCache] WiFi not connected; cannot fetch iconId='" + iconId + "'");
        return false;
    }

    // For application icons we use a synthetic iconId of the form
    // "app_<application_id>" and fetch from the dedicated
    // /api/v1/application-icons/{application_id}.png endpoint. For all
    // other icon IDs we continue to use the legacy /api/v1/icons/{id}.png
    // endpoint that serves monochrome ESP32 icons.
    String url;
    if (iconId.startsWith("app_")) {
        // iconId may be of the form "app_<application_id>" or
        // "app_<application_id>_<version>". Strip any version/hash suffix
        // so we always call the canonical /application-icons/{id}.png
        // endpoint while still allowing versioned cache keys on disk.
        String appId = iconId.substring(4);
        int sep = appId.indexOf('_');
        if (sep >= 0) {
            appId = appId.substring(0, sep);
        }
        url = String("http://") + host + ":" + String(port) + "/api/v1/application-icons/" + appId + ".png";
    } else {
        url = String("http://") + host + ":" + String(port) + "/api/v1/icons/" + iconId + ".png";
    }

    Serial.println("[IconCache] Fetching iconId='" + iconId + "' from URL=" + url);

    HTTPClient http;
    http.begin(url);
    int httpCode = http.GET();
    if (httpCode != HTTP_CODE_OK) {
        Serial.println("[IconCache] HTTP GET failed for iconId='" + iconId + "' code=" + String(httpCode));
        http.end();
        return false;
    }

    Serial.println("[IconCache] HTTP GET OK for iconId='" + iconId + "', saving to '" + path + "'");

    WiFiClient* stream = http.getStreamPtr();
    File f = ICON_FS.open(path, "w");
    if (!f) {
        http.end();
        return false;
    }

    uint8_t buffer[512];
    int len = http.getSize();
    // If Content-Length is not provided or reported as 0, treat it as
    // "unknown length" and stream until the connection closes.
    if (len <= 0) {
        len = -1;
    }
    while (http.connected() && (len > 0 || len == -1)) {
        size_t avail = stream->available();
        if (avail) {
            int c = stream->readBytes(buffer, (avail > sizeof(buffer)) ? sizeof(buffer) : avail);
            f.write(buffer, c);
            if (len > 0) {
                len -= c;
            }
        } else {
            delay(1);
        }
    }

    f.close();
    http.end();
    return true;
}
