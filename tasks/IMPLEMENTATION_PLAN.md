# Implementation Plan

## Phase 1 - Python Project Skeleton

- Create package structure
- Add FastAPI app
- Add SQLite database bootstrap
- Add config loading
- Add logging
- Add basic dashboard placeholder
- Add tray app placeholder

## Phase 2 - Security Core

- Generate API UUID
- Generate API secret
- Generate tokens
- Hash PINs
- Hash pairing codes
- Implement HMAC signing/verifying
- Implement nonce cache
- Implement timestamp validation

## Phase 3 - Pairing

- Tray button: Add New Keypad
- Generate one-time pairing code
- Pairing session expiry
- UDP discovery broadcast
- `/pairing/hello`
- `/pairing/complete`
- Device record creation
- Initial PIN policy delivery

## Phase 4 - Device Config

- Pad config endpoint
- Config version endpoint
- Config history
- Layout generation
- Control Panel PIN policy
- Update pending flags

## Phase 5 - Button Pad

- Macro model
- Button model
- Button press endpoint
- SendInput implementation
- Key sequence macro execution
- Audit logging

## Phase 6 - Task Pad

- Process scanner
- Window scanner
- Priority app list
- App icon extraction/cache
- Task button layout
- Bring window to foreground

## Phase 7 - WebSocket

- Per-device WebSocket
- Config update pending event
- Task Pad update event
- Device revoked event
- Heartbeat/ping

## Phase 8 - Dashboard

- Device list
- Pairing page
- Pad editor
- Macro editor
- Task Pad profile editor
- PIN editor
- Security page
- Audit logs

## Phase 9 - ESP32 Firmware

- Wi-Fi setup
- Pairing discovery
- PIN keypad
- Control Panel
- Config download
- Button rendering
- Touch handling
- Signed button events
- WebSocket update listener

## Phase 10 - Packaging

- Windows startup
- Installer
- Backup/restore
- Logs
- Documentation
