# Windsurf Rules for DisplayPad Server

## Role

You are building a production-quality Windows-only Python application called **DisplayPad Server**.

The application manages ESP32 touchscreen display pads over Wi-Fi.

## Non-Negotiable Requirements

1. The app must run on Windows only.
2. Use Python for the Windows API/server.
3. Use FastAPI for the API.
4. Use SQLite for local storage.
5. Use a system tray app.
6. Support multiple ESP32 pads.
7. Every pad must have a unique identity.
8. Pairing must use a fresh one-time code every time.
9. Pairing codes must expire and be single-use.
10. Each pad must have a Control Panel PIN.
11. Default Control Panel PIN is `00000000`.
12. PINs are numeric only and up to 8 digits.
13. Prefer exactly 8-digit PINs.
14. Never store plain-text PINs.
15. Never store plain-text device tokens.
16. Every button press must be authenticated.
17. Support Button Pad mode and Task Pad mode.
18. Support 6 to 32 buttons per device.
19. API calculates button layout and sends coordinates.
20. ESP32 must keep last known good config.
21. ESP32 must always check for latest config on startup.
22. API must notify pads of pending config updates over WebSocket.
23. Macro execution must be allowlisted.
24. Dangerous macros must support confirmation/permission flags.
25. Audit security-sensitive actions.

## Coding Style

- Use clear module boundaries.
- Use type hints.
- Use dataclasses or Pydantic models where useful.
- Prefer explicit names over clever code.
- Keep secrets out of logs.
- Keep Windows-specific code inside `src/displaypad_server/windows`.
- Keep crypto/security code inside `src/displaypad_server/core/security.py` and `core/crypto.py`.
- Keep API route files small.
- Write tests for security-critical functions.

## Security Rules

- Use `secrets` module for random tokens and codes.
- Hash PINs using a strong password hashing method.
- Use HMAC-SHA256 for signed ESP32 events.
- Validate timestamps and nonces.
- Reject replayed events.
- Rate-limit button presses.
- Pairing mode must be off by default.
- Pairing mode must expire automatically.
- Device revoke must immediately block future commands.
- Config updates must be versioned and signed.
- Logs must never include raw tokens, PINs, or HMAC secrets.

## UI Rules

- The tray app must include:
  - Open Dashboard
  - Add New Keypad
  - Paired Keypads
  - Button Pads
  - Task Pads
  - Security
  - Logs
  - Restart API
  - Exit

## ESP32 Rules

The ESP32 firmware design must include:

- 20-second startup Control Panel access screen
- Hidden dropdown menu by swipe down or top-bar long press
- Numeric PIN keypad
- Wi-Fi setup
- Device diagnostics
- Host/API diagnostics
- Reset Pairing Only
- Reset Wi-Fi Only
- Factory Reset
- Generate New Pad Profile
- Pairing screen that displays host name and IP
- Pairing code entry
- Latest config check on every boot
- WebSocket update listener

## Do Not Do

- Do not make this cross-platform.
- Do not use cloud services.
- Do not execute arbitrary unauthenticated commands.
- Do not trust ESP32-provided button layouts.
- Do not let ESP32 define macros.
- Do not hardcode secrets.
- Do not log credentials.
