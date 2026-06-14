# Windows Application Design

## Application Type

Windows-only Python application.

## Components

```text
System tray app
FastAPI server
SQLite database
Local admin dashboard
Windows macro executor
Task/window scanner
Icon extractor
```

## Tray Menu

```text
DisplayPad Server
 ├── Open Dashboard
 ├── Add New Keypad
 ├── Paired Keypads
 ├── Button Pads
 ├── Task Pads
 ├── Security
 ├── Logs
 ├── Restart API
 └── Exit
```

## Dashboard Pages

```text
Home
Devices
Pairing
Button Pads
Task Pads
Macros
Security
Audit Logs
Settings
Backup/Restore
```

## Windows APIs Needed

Use Python wrappers / ctypes / pywin32 for:

```text
SendInput
EnumWindows
GetWindowText
SetForegroundWindow
ShowWindow
GetWindowThreadProcessId
ExtractIconEx
```

## Startup

Support:

```text
Run at login
Windows service mode later
Tray mode first
```

## Macro Execution

Macro execution must happen only after:

```text
Device authenticated
Button assigned
Macro enabled
Permission allowed
Rate limit passed
```
