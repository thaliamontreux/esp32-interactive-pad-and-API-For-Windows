# API Specification

Base URL:

```text
https://<windows-host>:7443/api/v1
```

WebSocket:

```text
wss://<windows-host>:7443/api/v1/pads/{pad_id}/ws
```

## Pairing Hello

```http
POST /pairing/hello
```

Request:

```json
{
  "pad_uuid": "pad-8A72F91C",
  "screen": {
    "width": 240,
    "height": 320,
    "driver": "ILI9341",
    "touch": true
  },
  "firmware": "0.1.0"
}
```

Response:

```json
{
  "pairing_allowed": true,
  "api_name": "OFFICE-PC",
  "api_uuid": "api-office-pc",
  "api_ip": "192.168.2.50",
  "api_port": 7443,
  "code_required": true,
  "expires_in": 120
}
```

## Pairing Complete

```http
POST /pairing/complete
```

Request:

```json
{
  "pad_uuid": "pad-8A72F91C",
  "pairing_code": "482913",
  "screen": {
    "width": 240,
    "height": 320,
    "driver": "ILI9341"
  },
  "firmware": "0.1.0"
}
```

Response:

```json
{
  "paired": true,
  "pad_id": "pad-office-left",
  "device_token": "secure-issued-token",
  "api_uuid": "api-office-pc",
  "api_host": "OFFICE-PC.local",
  "api_ip_backup": "192.168.2.50",
  "api_port": 7443,
  "api_fingerprint": "SHA256_CERT_FINGERPRINT",
  "control_panel_pin": {
    "enabled": true,
    "pin_length": 8,
    "pin_hash": "stored-hash-value",
    "default_pin_active": false,
    "max_attempts": 5,
    "lockout_seconds": 300
  }
}
```

## Get Config Version

```http
GET /pads/{pad_id}/config/version
```

Response:

```json
{
  "pad_id": "pad-office-left",
  "config_version": 43,
  "updated_at": "2026-06-07T13:22:00Z",
  "update_required": true
}
```

## Get Pad Config

```http
GET /pads/{pad_id}/config
```

Response:

```json
{
  "pad_id": "pad-office-left",
  "name": "Office Left Pad",
  "pad_mode": "button_pad",
  "button_count": 12,
  "config_version": 43,
  "control_panel_pin": {
    "enabled": true,
    "pin_length": 8,
    "pin_hash": "stored-hash-value",
    "default_pin_active": false,
    "max_attempts": 5,
    "lockout_seconds": 300
  },
  "screen": {
    "width": 240,
    "height": 320,
    "rotation": 0
  },
  "layout": {
    "columns": 3,
    "rows": 4
  },
  "buttons": [
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
  ]
}
```

## Button Press

```http
POST /pads/{pad_id}/press
```

Request:

```json
{
  "slot": 1,
  "press_type": "tap",
  "timestamp": 1780840000,
  "nonce": "random-nonce",
  "signature": "hmac-sha256"
}
```

## Config Applied

```http
POST /pads/{pad_id}/config/applied
```

Request:

```json
{
  "config_version": 43,
  "status": "applied"
}
```

## Config Update Failed

```http
POST /pads/{pad_id}/config/update-failed
```

Request:

```json
{
  "current_version": 42,
  "failed_version": 43,
  "reason": "Invalid PIN policy"
}
```

## Change Device PIN

```http
POST /pads/{pad_id}/pin
```

Request:

```json
{
  "new_pin": "12345678"
}
```

## WebSocket Events

API to ESP32:

```json
{
  "type": "config_update_pending",
  "pad_id": "pad-office-left",
  "config_version": 44,
  "message": "New config available"
}
```

```json
{
  "type": "task_pad_update",
  "pad_id": "pad-office-left",
  "tasks": []
}
```

```json
{
  "type": "device_revoked",
  "message": "This device has been revoked"
}
```
