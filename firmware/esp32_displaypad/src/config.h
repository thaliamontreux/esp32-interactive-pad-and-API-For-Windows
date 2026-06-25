#ifndef DISPLAYPAD_CONFIG_H
#define DISPLAYPAD_CONFIG_H

#include <Arduino.h>

// Display settings - LANDSCAPE MODE (rotated 90°)
#define SCREEN_WIDTH 320
#define SCREEN_HEIGHT 240
#define SCREEN_DRIVER "ILI9341"
#define TFT_ROTATION 1  // 1 = 90° rotation (landscape)
#define TFT_BL 21  // Backlight pin (LED on this board)

// Default API settings (will be overwritten after pairing)
#define DEFAULT_API_PORT 7443
#define DEFAULT_API_TIMEOUT 10000

// Firmware version string for diagnostics and logging. Bump this when
// shipping new firmware so the API and GUI can distinguish versions.
#define FW_VERSION "0.1.0"

// Pin settings
#define DEFAULT_PIN "0000"
#define PIN_MAX_LENGTH 4
#define PIN_MAX_ATTEMPTS 5
#define PIN_LOCKOUT_SECONDS 300

// Timing
#define STARTUP_CONTROL_PANEL_WINDOW_MS 20000
#define PAIRING_CODE_LENGTH 6
#define PAIRING_TIMEOUT_MS 120000
#define CONFIG_CHECK_INTERVAL_MS 30000
#define WEBSOCKET_RECONNECT_DELAY_MS 5000
#define TOUCH_DEBOUNCE_MS 50

// Button layout
#define MIN_BUTTONS 6
#define MAX_BUTTONS 32

// Colors (16-bit RGB565)
#define COLOR_BLACK 0x0000
#define COLOR_WHITE 0xFFFF
#define COLOR_RED 0xF800
#define COLOR_GREEN 0x07E0
#define COLOR_BLUE 0x001F
#define COLOR_YELLOW 0xFFE0
#define COLOR_CYAN 0x07FF
#define COLOR_MAGENTA 0xF81F
#define COLOR_GRAY 0x8410
#define COLOR_DARK_GRAY 0x4208
#define COLOR_BUTTON_BG 0x780F
#define COLOR_BUTTON_TEXT 0xFFFF
#define COLOR_ACCENT 0x07E0

// Additional theme colors for cyberpunk-style UI on the ESP32
#define COLOR_BG_DARK       0x0841  // very dark blue/teal background
#define COLOR_BG_DARKER     0x0008  // near-black for panels/stripes
#define COLOR_BG_MID        0x2108  // slightly lighter industrial panel
#define COLOR_NEON_PURPLE   0x780F  // bright purple accent
#define COLOR_NEON_CYAN     0x07FF  // alias of cyan, used as primary neon
#define COLOR_NEON_YELLOW   0xFFE0  // bright yellow accent

// Debug
#define DEBUG_SERIAL Serial
#define DEBUG_ENABLED true

// NVS keys
#define NVS_NAMESPACE "displaypad"
#define NVS_KEY_PAD_UUID "pad_uuid"
#define NVS_KEY_PAD_SECRET "pad_secret"
#define NVS_KEY_API_UUID "api_uuid"
#define NVS_KEY_API_HOST "api_host"
#define NVS_KEY_API_IP "api_ip"
#define NVS_KEY_API_PORT "api_port"
#define NVS_KEY_DEVICE_TOKEN "device_token"
#define NVS_KEY_CONFIG_VERSION "config_version"
#define NVS_KEY_PIN_HASH "pin_hash"
#define NVS_KEY_PAIRED "paired"
#define NVS_KEY_WIFI_SSID "wifi_ssid"
#define NVS_KEY_WIFI_PASS "wifi_pass"
// User-configured timezone offset (minutes from UTC); 0 means use server
// provided offset.
#define NVS_KEY_TIME_OFFSET "time_offset"
// Whether to apply US DST rules automatically to the stored base offset.
#define NVS_KEY_US_AUTO_DST "us_auto_dst"
// Diagnostics: count how many times we had to fall back from last-known API IP
// to full network discovery because direct connection failed for 5 minutes.
#define NVS_KEY_LAST_IP_FAILS "last_ip_fails"
// Connection mode: 0 = WiFi, 1 = Bluetooth, 2 = Auto (prefer BLE, fallback WiFi)
#define NVS_KEY_CONN_MODE "conn_mode"

#endif
