# ESP32 DisplayPad Firmware

Complete firmware for ESP32-WROOM-32 with ILI9341 240x320 touchscreen display.

## Hardware Requirements

- **MCU**: ESP32-WROOM-32
- **Display**: ILI9341 240x320 TFT LCD
- **Touch**: XPT2046 resistive touch controller
- **Framework**: Arduino with PlatformIO

## Pin Connections (Default)

| Signal | GPIO |
|--------|------|
| TFT_MISO | 19 |
| TFT_MOSI | 23 |
| TFT_SCLK | 18 |
| TFT_CS   | 15 |
| TFT_DC   | 2  |
| TFT_RST  | 4  |
| TOUCH_CS | 21 |

## Building

### Prerequisites

1. Install [PlatformIO](https://platformio.org/)
2. Connect ESP32 to USB

### Build and Upload

```bash
cd firmware/esp32_displaypad

# Build
pio run

# Upload
pio run --target upload

# Monitor serial output
pio device monitor
```

## Features Implemented

### Core Features
- ✅ 20-second startup Control Panel access window
- ✅ Hidden dropdown menu (long-press top bar)
- ✅ Numeric PIN keypad (0-9, Clear, Enter)
- ✅ Default PIN: `00000000`
- ✅ WiFi setup with AP mode captive portal
- ✅ Pairing discovery with Windows API
- ✅ Host/IP display
- ✅ Device diagnostics screen
- ✅ NVS secure config storage
- ✅ Dynamic button rendering
- ✅ Touch event handling
- ✅ HMAC-SHA256 signed button events
- ✅ WebSocket real-time updates
- ✅ Config version checking
- ✅ Reset pairing
- ✅ Reset WiFi
- ✅ Factory reset
- ✅ Generate new pad profile

### State Machine

1. **BOOT** - Initialize and check WiFi status
2. **STARTUP_WINDOW** - 20-second window for Control Panel access
3. **WIFI_SETUP** - AP mode for WiFi configuration
4. **DISCOVERY_WAITING** - Scan network and wait for server assignment
5. **NORMAL_OPERATION** - Render buttons and handle touches
6. **CONTROL_PANEL** - Settings and diagnostics menu
7. **ERROR** - Error recovery state

## API Communication

The firmware communicates with the Windows DisplayPad Server API:

- **Discovery Hello**: `POST /api/v1/discovery/hello`
- **Auto-Assign**: `POST /api/v1/discovery/assign`
- **Config Check**: `GET /api/v1/pads/{id}/config/version`
- **Get Config**: `GET /api/v1/pads/{id}/config`
- **Button Press**: `POST /api/v1/pads/{id}/press`
- **WebSocket**: `ws://{host}:7443/api/v1/pads/{id}/ws`

Authentication is via simple headers:

- `X-Pad-UUID`: pad UUID
- `X-Device-Token`: device token assigned during discovery/auto-assign

No timestamps, nonces, or HMAC signatures are used.

## Layout and Rendering

- Screen: 320×240 landscape
- Title bar: 36 px high (Y = 0..35)
- Button area: 320×204 starting at Y = 36
- Padding: 8 px inside the button area
- Gap: 8 px for small layouts, 6 px for dense layouts

Dynamic grid selection for 1–32 buttons:

| Buttons | Grid | Gap |
| ------: | ---- | --- |
|       1 | 1×1  | 8   |
|       2 | 2×1  | 8   |
|       3 | 3×1  | 8   |
|       4 | 2×2  | 8   |
|     5–6 | 3×2  | 8   |
|     7–8 | 4×2  | 8   |
|       9 | 3×3  | 8   |
|   10–12 | 4×3  | 8   |
|   13–16 | 4×4  | 6   |
|   17–20 | 5×4  | 6   |
|   21–24 | 6×4  | 6   |
|      25 | 5×5  | 6   |
|   26–30 | 6×5  | 6   |
|   31–32 | 8×4  | 6   |

Grid math (server and firmware use the same rules):

```cpp
buttonAreaY = 36;
buttonAreaH = 240 - 36;  // 204

buttonW = (320 - padding * 2 - gap * (cols - 1)) / cols;
buttonH = (204 - padding * 2 - gap * (rows - 1)) / rows;

buttonX = padding + col * (buttonW + gap);
buttonY = buttonAreaY + padding + row * (buttonH + gap);
```

Rules:

- Buttons are never drawn above Y = 36 and never overlap the title bar.
- Buttons do not overlap each other.
- For more than 16 buttons, smaller text/icons are recommended.
- For 21+ buttons, icons are preferred over long labels.
- Labels are truncated with `...` if they do not fit.
- If button count exceeds 32, paging should be used instead of further shrinking.

## File Structure

```
src/
  config.h           - Configuration constants
  storage.h/cpp      - NVS secure storage
  display.h/cpp      - TFT display interface
  wifi_manager.h/cpp - WiFi connection and AP mode
  pin_keypad.h/cpp   - PIN entry UI
  api_client.h/cpp   - HTTP/WebSocket API client
  button_renderer.h/cpp - Button rendering and touch
  control_panel.h/cpp - Settings menu UI
  main.cpp           - Main application and state machine
```
