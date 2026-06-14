#include "storage.h"
#include <esp_random.h>

SecureStorage storage;

SecureStorage::SecureStorage() : initialized(false) {}

bool SecureStorage::begin() {
    initialized = prefs.begin(NVS_NAMESPACE, false);
    return initialized;
}

void SecureStorage::end() {
    prefs.end();
    initialized = false;
}

bool SecureStorage::setPadUUID(const String& uuid) {
    return prefs.putString(NVS_KEY_PAD_UUID, uuid) > 0;
}

String SecureStorage::getPadUUID() {
    return prefs.getString(NVS_KEY_PAD_UUID, "");
}

bool SecureStorage::setPadSecret(const String& secret) {
    return prefs.putString(NVS_KEY_PAD_SECRET, secret) > 0;
}

String SecureStorage::getPadSecret() {
    return prefs.getString(NVS_KEY_PAD_SECRET, "");
}

bool SecureStorage::setApiUUID(const String& uuid) {
    return prefs.putString(NVS_KEY_API_UUID, uuid) > 0;
}

String SecureStorage::getApiUUID() {
    return prefs.getString(NVS_KEY_API_UUID, "");
}

bool SecureStorage::setApiHost(const String& host) {
    return prefs.putString(NVS_KEY_API_HOST, host) > 0;
}

String SecureStorage::getApiHost() {
    return prefs.getString(NVS_KEY_API_HOST, "");
}

bool SecureStorage::setApiIP(const String& ip) {
    return prefs.putString(NVS_KEY_API_IP, ip) > 0;
}

String SecureStorage::getApiIP() {
    return prefs.getString(NVS_KEY_API_IP, "");
}

bool SecureStorage::setApiPort(uint16_t port) {
    return prefs.putUShort(NVS_KEY_API_PORT, port) > 0;
}

uint16_t SecureStorage::getApiPort() {
    return prefs.getUShort(NVS_KEY_API_PORT, DEFAULT_API_PORT);
}

bool SecureStorage::setDeviceToken(const String& token) {
    return prefs.putString(NVS_KEY_DEVICE_TOKEN, token) > 0;
}

String SecureStorage::getDeviceToken() {
    return prefs.getString(NVS_KEY_DEVICE_TOKEN, "");
}

bool SecureStorage::setConfigVersion(uint32_t version) {
    return prefs.putUInt(NVS_KEY_CONFIG_VERSION, version) > 0;
}

uint32_t SecureStorage::getConfigVersion() {
    return prefs.getUInt(NVS_KEY_CONFIG_VERSION, 0);
}

bool SecureStorage::setPINHash(const String& hash) {
    return prefs.putString(NVS_KEY_PIN_HASH, hash) > 0;
}

String SecureStorage::getPINHash() {
    return prefs.getString(NVS_KEY_PIN_HASH, "");
}

bool SecureStorage::setWiFiSSID(const String& ssid) {
    return prefs.putString(NVS_KEY_WIFI_SSID, ssid) > 0;
}

String SecureStorage::getWiFiSSID() {
    return prefs.getString(NVS_KEY_WIFI_SSID, "");
}

bool SecureStorage::setWiFiPass(const String& pass) {
    return prefs.putString(NVS_KEY_WIFI_PASS, pass) > 0;
}

String SecureStorage::getWiFiPass() {
    return prefs.getString(NVS_KEY_WIFI_PASS, "");
}

bool SecureStorage::setLastIpFailureCount(uint32_t count) {
    return prefs.putUInt(NVS_KEY_LAST_IP_FAILS, count) > 0;
}

uint32_t SecureStorage::getLastIpFailureCount() {
    return prefs.getUInt(NVS_KEY_LAST_IP_FAILS, 0);
}

bool SecureStorage::setPaired(bool paired) {
    return prefs.putBool(NVS_KEY_PAIRED, paired);
}

bool SecureStorage::isPaired() {
    return prefs.getBool(NVS_KEY_PAIRED, false);
}

bool SecureStorage::factoryReset() {
    // Clear all keys
    prefs.clear();
    // Regenerate pad profile
    return generateNewProfile();
}

bool SecureStorage::generateNewProfile() {
    // Generate new pad UUID
    uint8_t uuid_bytes[8];
    esp_fill_random(uuid_bytes, 8);
    char uuid_str[17];
    sprintf(uuid_str, "%02X%02X%02X%02X%02X%02X%02X%02X",
            uuid_bytes[0], uuid_bytes[1], uuid_bytes[2], uuid_bytes[3],
            uuid_bytes[4], uuid_bytes[5], uuid_bytes[6], uuid_bytes[7]);

    // Generate new pad secret
    uint8_t secret_bytes[32];
    esp_fill_random(secret_bytes, 32);
    char secret_str[65];
    for (int i = 0; i < 32; i++) {
        sprintf(&secret_str[i * 2], "%02X", secret_bytes[i]);
    }

    if (!setPadUUID(String("pad-") + uuid_str)) return false;
    if (!setPadSecret(secret_str)) return false;

    // Reset other values
    setPaired(false);
    setApiUUID("");
    setApiHost("");
    setApiIP("");
    setDeviceToken("");
    setConfigVersion(0);
    setPINHash("");
    setLastIpFailureCount(0);

    return true;
}
