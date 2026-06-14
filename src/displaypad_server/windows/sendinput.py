"""Windows SendInput implementation for macro execution."""

import ctypes
import time
from typing import Literal

# Windows API constants
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# Virtual key codes for common keys
VK_CODES: dict[str, int] = {
    # Letters
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45, "f": 0x46,
    "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A, "k": 0x4B, "l": 0x4C,
    "m": 0x4D, "n": 0x4E, "o": 0x4F, "p": 0x50, "q": 0x51, "r": 0x52,
    "s": 0x53, "t": 0x54, "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58,
    "y": 0x59, "z": 0x5A,
    # Numbers
    "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
    "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
    # Function keys
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
    "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
    "f11": 0x7A, "f12": 0x7B,
    # Special keys
    "enter": 0x0D, "return": 0x0D, "tab": 0x09, "space": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "escape": 0x1B, "esc": 0x1B,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "insert": 0x2D, "print": 0x2C, "scroll": 0x91, "pause": 0x13,
    # Modifiers
    "shift": 0x10, "ctrl": 0x11, "control": 0x11, "alt": 0x12,
    "lshift": 0xA0, "rshift": 0xA1, "lctrl": 0xA2, "rctrl": 0xA3,
    "lalt": 0xA4, "ralt": 0xA5,
    # Windows keys
    "win": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    # Menu
    "menu": 0x5D, "apps": 0x5D,
    # Punctuation
    "semicolon": 0xBA, "equals": 0xBB, "comma": 0xBC, "minus": 0xBD,
    "period": 0xBE, "slash": 0xBF, "backtick": 0xC0,
    "lbracket": 0xDB, "backslash": 0xDC, "rbracket": 0xDD, "quote": 0xDE,
    # Numpad
    "numlock": 0x90, "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62,
    "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66,
    "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69,
    "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
    "decimal": 0x6E, "divide": 0x6F,
    # Media keys
    "play": 0xB3, "stop": 0xB2, "prev": 0xB1, "next": 0xB0,
    "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD,
}

# Windows C structures
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        # dwExtraInfo is an ULONG_PTR; use c_ulonglong for safety on 64-bit.
        ("dwExtraInfo", ctypes.c_ulonglong),
    ]


class INPUT_I(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", INPUT_I),
    ]


# Windows API functions
user32 = ctypes.WinDLL("user32", use_last_error=True)

# keybd_event is deprecated but simpler and sufficient for our macro use case.
_keybd_event = user32.keybd_event
_keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_uint, ctypes.c_ulonglong]
_keybd_event.restype = None


def _send_key_event(vk_code: int, key_up: bool = False) -> None:
    """Send a single key event using keybd_event."""
    flags = KEYEVENTF_EXTENDEDKEY if vk_code >= 0x100 else 0
    if key_up:
        flags |= KEYEVENTF_KEYUP

    # bVk is a BYTE; bScan left as 0 (let Windows translate), dwFlags controls
    # press/release, dwExtraInfo unused here.
    _keybd_event(ctypes.c_ubyte(vk_code), ctypes.c_ubyte(0), ctypes.c_uint(flags), ctypes.c_ulonglong(0))


def _key_to_vk(key: str) -> int | None:
    """Convert key string to virtual key code."""
    key_lower = key.lower()
    if key_lower in VK_CODES:
        return VK_CODES[key_lower]

    # Single character lookup
    if len(key) == 1:
        char = key_lower
        if char in VK_CODES:
            return VK_CODES[char]
        # Use VkKeyScan for unknown characters
        result = user32.VkKeyScanA(ord(char))
        if result != -1:
            return result & 0xFF

    return None


def send_key(key: str) -> None:
    """Send a single key press and release."""
    vk = _key_to_vk(key)
    if vk is None:
        raise ValueError(f"Unknown key: {key}")

    _send_key_event(vk, key_up=False)
    _send_key_event(vk, key_up=True)


def send_key_combo(keys: list[str]) -> None:
    """Send a key combination (e.g., ['ctrl', 'c'])."""
    vks: list[int] = []
    for key in keys:
        vk = _key_to_vk(key)
        if vk is None:
            raise ValueError(f"Unknown key: {key}")
        vks.append(vk)

    # Press all keys
    for vk in vks:
        _send_key_event(vk, key_up=False)

    # Release in reverse order
    for vk in reversed(vks):
        _send_key_event(vk, key_up=True)


def send_key_sequence(keys: list[str], delay_ms: int = 10) -> None:
    """Send a sequence of key presses with optional delay."""
    for key in keys:
        send_key(key)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)


def send_text(text: str) -> None:
    """Type a string of text."""
    for char in text:
        vk = _key_to_vk(char)
        if vk is not None:
            _send_key_event(vk, key_up=False)
            _send_key_event(vk, key_up=True)
        else:
            # For characters without VK codes, we might need a more complex approach
            # This is a simplified version
            pass


def execute_macro(macro_type: str, payload: dict) -> bool:
    """Execute a macro based on type and payload."""
    try:
        if macro_type == "key_sequence_v2":
            # Advanced key sequence: payload contains a list of "records",
            # each with one or more key combos and an optional delay after the
            # record. Example payload:
            # {
            #   "records": [
            #       {"combos": [["alt", "ctrl", "f"], ["a"], ["t"]], "delay_after_ms": 5000},
            #       {"combos": [["d"], ["m"], ["a"]], "delay_after_ms": 3000}
            #   ]
            # }
            records = payload.get("records", [])
            if not isinstance(records, list):
                return False

            # Small fixed delay between individual combos so we don't
            # overwhelm the target system. This can be tuned later if needed.
            combo_delay_ms = payload.get("combo_delay_ms", 30) or 0
            try:
                combo_delay_ms = int(combo_delay_ms)
            except (TypeError, ValueError):
                combo_delay_ms = 30
            combo_delay_ms = max(0, min(combo_delay_ms, 1000))

            executed_any = False
            for rec in records:
                if not isinstance(rec, dict):
                    continue

                combos = rec.get("combos") or []
                # An empty or missing combos list is treated as end-of-macro.
                if not combos:
                    break

                for combo in combos:
                    if not combo:
                        continue

                    # Normalise combo representation to a list of strings.
                    if isinstance(combo, str):
                        keys = [combo]
                    else:
                        keys = [str(k) for k in combo]

                    try:
                        # Debug: log each combo before sending
                        print(f"[SENDINPUT] key_sequence_v2 combo={keys}", flush=True)
                        send_key_combo(keys)
                        executed_any = True
                    except Exception as e:
                        # Skip invalid combos but continue executing the rest.
                        print(f"[SENDINPUT] combo failed keys={keys} error={e}", flush=True)
                        continue

                    if combo_delay_ms > 0:
                        time.sleep(combo_delay_ms / 1000.0)

                # Per-record delay before moving to the next record, clamped
                # to a maximum of 30 seconds.
                delay_after_ms = rec.get("delay_after_ms", 0) or 0
                try:
                    delay_after_ms = int(delay_after_ms)
                except (TypeError, ValueError):
                    delay_after_ms = 0
                delay_after_ms = max(0, min(delay_after_ms, 30000))
                if delay_after_ms > 0:
                    time.sleep(delay_after_ms / 1000.0)

            return executed_any

        if macro_type == "key_sequence":
            keys = payload.get("keys", [])
            delay = payload.get("delay_ms", 10)
            send_key_sequence(keys, delay)
            return True

        elif macro_type == "text_string":
            text = payload.get("text", "")
            send_text(text)
            return True

        elif macro_type == "key_combo":
            keys = payload.get("keys", [])
            send_key_combo(keys)
            return True

        elif macro_type == "media_key":
            key = payload.get("key", "")
            if key:
                send_key(key)
                return True

        else:
            # Other macro types not yet implemented
            return False

    except Exception:
        return False


def send_key_sequence_placeholder(sequence: list[dict]) -> None:
    """Placeholder for Windows SendInput implementation."""
    raise NotImplementedError("SendInput implementation pending")
