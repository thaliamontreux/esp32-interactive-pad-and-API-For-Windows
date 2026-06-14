# Windsurf Master Prompt

Build the project in this repository exactly as specified.

Project name: DisplayPad Server

Goal:
Create a Windows-only Python app that manages ESP32 touchscreen display pads over Wi-Fi. Pads can be Button Pads for macros or Task Pads for running applications. The app must be secure, multi-device, and managed through a tray app and local dashboard.

Important files to follow:

- `.windsurf/rules.md`
- `docs/PROJECT_SPEC.md`
- `docs/security/SECURITY_MODEL.md`
- `docs/api/API_SPEC.md`
- `docs/database/SCHEMA.md`
- `docs/windows/WINDOWS_APP_DESIGN.md`
- `docs/esp32/ESP32_FIRMWARE_SPEC.md`
- `tasks/IMPLEMENTATION_PLAN.md`

Start by implementing Phase 1 and Phase 2 only. Do not skip security. Do not hardcode secrets. Keep Windows-specific code isolated.
