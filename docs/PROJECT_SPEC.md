# DisplayPad Server Full Project Specification

## 1. Overview

DisplayPad Server is a Windows-only Python application that manages ESP32 touchscreen display pads.

Each pad can be configured as:

```text
Button Pad = macro keypad
Task Pad   = active application/task keypad
```

The Windows API controls:

```text
Pairing
Security
Device configuration
Button count
Button layout
Macro definitions
Task Pad app list
Icons
Control Panel PIN policy
Config updates
Audit logging
```

The ESP32 controls:

```text
Touchscreen display
Wi-Fi setup
PIN entry
Pairing prompts
Diagnostics
Local reset actions
Rendering API-provided buttons
Sending signed touch/button events
```

## 2. Main Architecture

```text
ESP32 Display Pad
    ↓ Wi-Fi HTTPS / WebSocket
DisplayPad Server API on Windows
    ↓
Macro Engine / Task Engine
    ↓
Windows SendInput / Window Focus / App Launch
```

## 3. Supported Screen Profiles

| Size | Resolution | Driver | Notes |
|---|---:|---|---|
| 2.0" | 240x320 | ST7789 | Compact GUI |
| 2.4" | 240x320 | ILI9341 | Extremely common |
| 2.8" | 240x320 | ILI9341/ST7789 | Popular touch size |
| 3.2" | 320x480 | ILI9488 | Larger UI |
| 3.5" | 320x480 | ILI9488 | Dashboard size |
| 4.0" | 320x480 | ST7796/ILI9488 | Control panels |
| 4.3" | 480x272 | RGB Panels | ESP32-S3 projects |
| 4.3" | 480x800 | RGB Panels | ESP32-S3 projects |
| 5.0"+ | 800x480 | RGB/Parallel | Usually ESP32-S3 |

Primary target:

```text
ESP32-WROOM-32
ILI9341
240x320
```

## 4. Pad Modes

### Button Pad

Displays configured macro buttons.

Macro types:

```text
key_sequence
text_string
launch_program
run_script
open_url
system_command
media_key
window_action
```

### Task Pad

Displays currently running apps and priority apps.

The API scans Windows processes/windows, extracts icons, and sends app/task buttons to the ESP32.  
Touching a task button brings the selected window to the foreground.

## 5. Button Counts

Each pad supports:

```text
Minimum: 6 buttons
Maximum: 32 buttons
```

Common 240x320 layouts:

```text
6  = 2 x 3
8  = 2 x 4
9  = 3 x 3
12 = 3 x 4
16 = 4 x 4
20 = 4 x 5
24 = 4 x 6
32 = 4 x 8
```

The API sends exact coordinates:

```json
{
  "slot": 1,
  "x": 0,
  "y": 0,
  "w": 80,
  "h": 80,
  "label": "Lock",
  "icon_id": "lock",
  "action_id": "lock_pc"
}
```

## 6. ESP32 Control Panel

Access methods:

```text
1. 20-second startup access window
2. Hidden dropdown menu by swipe down from top
3. Long press top status bar
4. Failure screen when API is unreachable
```

Control Panel functions:

```text
Wi-Fi setup
Pairing setup
Device diagnostics
Host/API diagnostics
Config refresh
Reconnect API
Reset Pairing Only
Reset Wi-Fi Only
Factory Reset
Generate New Pad Profile
```

## 7. Control Panel PIN

Each device has a Control Panel PIN.

```text
Default PIN: 00000000
Digits: 0-9 only
Maximum length: 8 digits
Recommended policy: exactly 8 digits
```

The API owns the PIN policy.  
The ESP32 uses the default PIN until it receives its API-provided PIN policy.

Numeric keypad:

```text
[1] [2] [3]
[4] [5] [6]
[7] [8] [9]
[0] [Clear] [Enter]
```

## 8. Pairing

Pairing starts from the Windows tray app:

```text
Add New Keypad
```

The API generates a fresh one-time pairing code every time.

The ESP32 discovers the host and shows:

```text
Host name
Host IP
API UUID/fingerprint
Pairing code entry prompt
```

The user enters the pairing code on the ESP32.

## 9. Configuration Updates

Every registered ESP32 must:

```text
Check config version at startup
Download latest config if changed
Open WebSocket after authentication
Listen for config_update_pending messages
Validate config before applying
Keep last known good config
Report failed updates
```

## 10. Windows Dashboard

Dashboard functions:

```text
View paired pads
Start pairing
Configure pad mode
Set button count
Assign macros
Set priority apps
Set Control Panel PIN per device
View default PIN warnings
Revoke device
View diagnostics
View logs
Backup/restore settings
```
