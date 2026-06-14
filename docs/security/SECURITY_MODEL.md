# Security Model

## Threats

The system must protect against:

```text
Unauthorized devices
Fake API hosts
Replay attacks
Button press forgery
Pairing hijack
Lost/stolen pads
PIN guessing
Config tampering
Accidental dangerous macros
Secret exposure in logs
```

## Device Identity

On first boot, the ESP32 generates:

```text
pad_uuid
pad_secret
```

These are stored in flash/NVS.

## API Identity

The Windows API generates:

```text
api_uuid
api_secret
TLS certificate/fingerprint
```

The ESP32 stores the API identity after pairing and must not trust a different API unless reset.

## Pairing

Pairing requirements:

```text
Fresh one-time pairing code every session
Short expiration, default 2 minutes
Single use only
Pairing mode off by default
Pairing mode started manually from tray/dashboard
Pairing code displayed on Windows
Code entered on ESP32
```

The pairing code is never the permanent device token.

## Tokens and PINs

Never store:

```text
Plain-text PINs
Plain-text pairing codes
Plain-text long-term tokens
```

Store:

```text
Hashed PINs
Hashed tokens
Hashed pairing codes
```

## Button Event Authentication

Each event must include:

```json
{
  "pad_id": "pad-office-left",
  "slot": 1,
  "event_id": "random-event-id",
  "timestamp": 1780840000,
  "nonce": "random-nonce",
  "signature": "hmac-sha256"
}
```

API verifies:

```text
Known pad
Pad enabled
Pad not revoked
Valid token/HMAC
Timestamp within allowed skew
Nonce has not been used
Slot assigned
Action allowed
Rate limit not exceeded
```

## PIN Lockout

Recommended:

```text
Max failed attempts: 5
Lockout: 300 seconds
```

## Revoke Device

Revoking a device must:

```text
Disable device token
Reject WebSocket
Reject button events
Mark pad revoked
Log audit event
Optionally notify connected pad to wipe pairing
```

## Dangerous Macros

Macros may be marked:

```text
normal
elevated
dangerous
```

Dangerous macros should support:

```text
Confirmation
PIN re-entry
Admin dashboard approval
Disable-all emergency switch
```

## Audit Events

Audit:

```text
Pairing started
Pairing completed
Pairing failed
Device revoked
PIN changed
Config changed
Macro executed
Macro denied
Replay detected
Invalid HMAC
Dashboard login
Backup/restore
```
