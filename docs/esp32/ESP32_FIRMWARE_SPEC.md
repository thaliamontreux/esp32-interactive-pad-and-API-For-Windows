# ESP32 Firmware Specification

## Hardware Target

```text
ESP32-WROOM-32
ILI9341 240x320 touchscreen
```

## Firmware Modules

```text
WiFiManager
ControlPanelUI
PinKeypadUI
PairingManager
SecureStorage
ApiClient
PadRenderer
TouchHandler
DiagnosticsScreen
ResetManager
ConfigUpdateManager
```

## Boot Flow

```text
Boot
 ↓
Show 20-second Control Panel access screen
 ↓
Load local identity
 ↓
If no Wi-Fi configured:
    Open Wi-Fi setup
 ↓
Connect Wi-Fi
 ↓
If not paired:
    Search for pairing host
 ↓
If paired:
    Connect to saved API hostname
    If hostname fails, try backup IP
 ↓
Authenticate
 ↓
Check config version
 ↓
Download latest config if changed
 ↓
Apply PIN policy if changed
 ↓
Open WebSocket
 ↓
Show PIN unlock if enabled
 ↓
Display Button Pad or Task Pad
 ↓
Listen for API update notifications
```

## Control Panel Access

```text
20-second startup window
Hidden swipe-down menu
Long-press top status bar
API failure screen
```

## PIN Keypad

```text
[1] [2] [3]
[4] [5] [6]
[7] [8] [9]
[0] [Clear] [Enter]
```

Default PIN:

```text
00000000
```

## Stored Config

```json
{
  "pad_uuid": "pad-8A72F91C",
  "pad_secret": "local-random-device-secret",
  "api_uuid": "api-office-pc",
  "api_host": "OFFICE-PC.local",
  "api_ip_backup": "192.168.2.50",
  "api_port": 7443,
  "api_fingerprint": "SHA256_CERT_FINGERPRINT",
  "device_token": "issued-by-api",
  "paired": true,
  "config_version": 43,
  "pin_policy": {
    "enabled": true,
    "pin_length": 8,
    "pin_hash": "stored-hash-value",
    "default_pin_active": false,
    "max_attempts": 5,
    "lockout_seconds": 300
  }
}
```

## Reset Options

```text
Reset Pairing Only
Reset Wi-Fi Only
Factory Reset
Generate New Pad Profile
```

All reset options require Control Panel PIN.

## Config Validation

Before applying config:

```text
Valid JSON
Correct pad_id
Valid button count 6-32
No duplicate slots
Coordinates fit screen
Valid PIN policy
Newer config version
Valid API signature
```
