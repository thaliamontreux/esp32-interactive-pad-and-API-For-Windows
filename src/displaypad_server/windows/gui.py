"""DisplayPad Server Windows GUI with Cyberpunk theme."""

import os
import sys
import time
import subprocess
from datetime import datetime, timezone
import requests
from datetime import datetime, timedelta
from typing import Optional
import ctypes
from ctypes import wintypes

# Suppress Qt CSS warnings (box-shadow not supported)
os.environ["QT_LOGGING_RULES"] = "qt.css.*=false"

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QGridLayout,
    QLineEdit, QComboBox, QSpinBox, QCheckBox, QTextEdit, QPlainTextEdit,
    QGroupBox, QSplitter, QListWidget, QListWidgetItem, QMessageBox,
    QFileDialog, QScrollArea, QDialog, QDialogButtonBox, QTabWidget,
    QSystemTrayIcon, QMenu, QColorDialog, QCompleter,
    QTableWidget, QTableWidgetItem, QInputDialog, QRadioButton, QButtonGroup
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize, QObject, QRectF
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QLinearGradient, QGradient, QBrush, QPixmap, QPainter, QPen, QAction

from displaypad_server.core.config import get_config as _get_config
from displaypad_server.db.database import connect as _db_connect
from displaypad_server.core.layout import generate_layout

# Cyberpunk Color Scheme
CYBERPUNK_COLORS = {
    "bg_dark": "#07060a",
    "bg_panel": "#14101b",
    "bg_elevated": "#1b1524",
    "bg_input": "#100c15",
    "neon_cyan": "#39d0ff",
    "neon_pink": "#ff4d9a",
    "neon_yellow": "#f8c555",
    "neon_green": "#55e39d",
    "neon_red": "#ff5d73",
    "neon_purple": "#a45cff",
    "text_white": "#f5f1fb",
    "text_gray": "#baaecd",
    "border_glow": "#8a5cff",
    "gothic_primary": "#8a5cff",
    "gothic_secondary": "#7a153f",
}


class _MacroEventBus(QObject):
    macros_changed = pyqtSignal()


MACRO_EVENT_BUS = _MacroEventBus()


if sys.platform == "win32":  # Session change / lock detection is Windows-only.
    # Original message-based approach (WM_WTSSESSION_CHANGE) symbols are kept
    # for reference, but the current implementation uses a safer polling-based
    # detection via OpenInputDesktop so we don't rely on nativeEvent wiring.
    WM_WTSSESSION_CHANGE = 0x02B1
    WTS_SESSION_LOCK = 0x7
    WTS_SESSION_UNLOCK = 0x8
    NOTIFY_FOR_THIS_SESSION = 0

    # Desktop-access flags for OpenInputDesktop. DESKTOP_SWITCHDESKTOP is
    # sufficient for determining whether the workstation is locked.
    DESKTOP_SWITCHDESKTOP = 0x0100

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _OpenInputDesktop = _user32.OpenInputDesktop
    _OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _OpenInputDesktop.restype = wintypes.HANDLE

    _CloseDesktop = _user32.CloseDesktop
    _CloseDesktop.argtypes = [wintypes.HANDLE]
    _CloseDesktop.restype = wintypes.BOOL


class SessionStateWatcher(QWidget):
    """Hidden widget that listens for Windows session lock/unlock.

    When the workstation is locked or unlocked, this widget will make a
    best-effort POST to the API's /api/v1/system/host_session_state
    endpoint so pads can blank/unblank their displays.
    """

    def __init__(self, api_port: int, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self._session_locked = False
        self._last_raw_locked = False
        self._last_raw_change_ts = time.monotonic()
        self._unlock_debounce_seconds = 5.0

        # Use a polling-based check for lock state under Windows by calling
        # OpenInputDesktop(DESKTOP_SWITCHDESKTOP). This avoids relying on
        # low-level nativeEvent plumbing that has been fragile across PyQt
        # versions.
        if sys.platform == "win32":
            from PyQt6.QtCore import QTimer

            self._poll_timer = QTimer(self)
            self._poll_timer.setInterval(1000)  # 1s
            self._poll_timer.timeout.connect(self._poll_lock_state)
            self._poll_timer.start()

    def _poll_lock_state(self) -> None:
        """Poll Windows for current lock state using OpenInputDesktop.

        When the workstation is locked, OpenInputDesktop(DESKTOP_SWITCHDESKTOP)
        will typically fail (return NULL). When unlocked, it should succeed.
        """

        if sys.platform != "win32":
            return

        locked = False
        try:
            # dwFlags=0, inherit=FALSE, desired access=DESKTOP_SWITCHDESKTOP
            hdesk = _OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
            if not hdesk:
                locked = True
            else:
                # Best-effort cleanup
                _CloseDesktop(hdesk)
        except Exception:
            # On any error, do not flip state spuriously; just keep last.
            return

        now = time.monotonic()
        if locked != self._last_raw_locked:
            self._last_raw_locked = locked
            self._last_raw_change_ts = now

        if locked and not self._session_locked:
            print(f"[SessionStateWatcher] Detected lock state change via polling: locked={locked}")
            self._send_session_state(True)
        elif (not locked and self._session_locked and
              now - self._last_raw_change_ts >= self._unlock_debounce_seconds):
            print(f"[SessionStateWatcher] Detected lock state change via polling: locked={locked}")
            self._send_session_state(False)

    def _send_session_state(self, locked: bool) -> None:
        if locked == self._session_locked:
            return
        self._session_locked = locked

        url = f"http://127.0.0.1:{self.api_port}/api/v1/system/host_session_state"
        try:
            print(f"[SessionStateWatcher] Posting host_session_state locked={locked} to {url}")
            resp = requests.post(url, json={"locked": locked}, timeout=2)
            print(f"[SessionStateWatcher] Response status={resp.status_code}")
        except Exception:
            # Best-effort only; failures here should not affect the GUI.
            pass

    def nativeEvent(self, eventType, message):  # type: ignore[override]
        if sys.platform == "win32":
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_WTSSESSION_CHANGE:
                    print(f"[SessionStateWatcher] Received WM_WTSSESSION_CHANGE wParam={msg.wParam}")
                    if msg.wParam == WTS_SESSION_LOCK:
                        self._send_session_state(True)
                    elif msg.wParam == WTS_SESSION_UNLOCK:
                        self._last_raw_locked = False
                        self._last_raw_change_ts = time.monotonic()
            except Exception:
                pass

        return super().nativeEvent(eventType, message)


class CyberpunkButton(QPushButton):
    """3D Cyberpunk styled button."""

    def __init__(self, text: str, color: str = "cyan", parent=None):
        super().__init__(text, parent)
        self.color_name = color
        self.color = CYBERPUNK_COLORS.get(f"neon_{color}", CYBERPUNK_COLORS["neon_cyan"])
        self.setFixedHeight(52)
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

    def update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.55 {CYBERPUNK_COLORS["bg_panel"]},
                    stop: 1 {self.color}18
                );
                border: 1px solid {self.color}B0;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 10px 18px;
                font-weight: bold;
                letter-spacing: 0.6px;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.45 {self.color}22,
                    stop: 1 {self.color}32
                );
                border: 1px solid {self.color};
            }}
            QPushButton:pressed {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self.color}40,
                    stop: 0.5 {self.color}28,
                    stop: 1 {CYBERPUNK_COLORS["bg_panel"]}
                );
            }}
        """)


class OutputMessagesDialog(QDialog):
    """Dialog for toggling output/logging categories via the API.

    This talks to /api/v1/logging/settings to fetch and update the
    category flags (e.g. taskpad, ble_bridge, wifi, app).
    """

    def __init__(self, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self.setWindowTitle("Output Messages")
        self.setModal(True)

        self._checkboxes: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)

        info_label = QLabel(
            "Select which informational message categories should be "
            "shown in the console. Critical errors are always shown.")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self._categories_container = QVBoxLayout()
        layout.addLayout(self._categories_container)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_settings()

    def _category_label(self, key: str) -> str:
        mapping = {
            "taskpad": "Taskpad",
            "ble_bridge": "Bluetooth Bridge",
            "wifi": "WiFi",
            "app": "Application",
        }
        if key in mapping:
            return mapping[key]
        # Fallback: humanize the key
        return key.replace("_", " ").title()

    def _load_settings(self) -> None:
        url = f"http://127.0.0.1:{self.api_port}/api/v1/logging/settings"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as e:  # pragma: no cover - best-effort GUI
            QMessageBox.critical(
                self,
                "Output Messages",
                f"Failed to load logging settings from API:\n{e}",
            )
            data = {}

        # Clear any existing checkboxes (if reloaded)
        for i in reversed(range(self._categories_container.count())):
            item = self._categories_container.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.setParent(None)

        self._checkboxes.clear()

        # Stable order: sort by label
        items = list(data.items())
        items.sort(key=lambda kv: self._category_label(kv[0]).lower())

        for key, enabled in items:
            cb = QCheckBox(self._category_label(key))
            cb.setChecked(bool(enabled))
            self._categories_container.addWidget(cb)
            self._checkboxes[key] = cb

    def on_accept(self) -> None:
        url = f"http://127.0.0.1:{self.api_port}/api/v1/logging/settings"
        payload = {key: cb.isChecked() for key, cb in self._checkboxes.items()}

        try:
            resp = requests.put(url, json=payload, timeout=5)
            resp.raise_for_status()
        except Exception as e:  # pragma: no cover - best-effort GUI
            QMessageBox.critical(
                self,
                "Output Messages",
                f"Failed to save logging settings to API:\n{e}",
            )
            return

        self.accept()


class PadPreviewWidget(QFrame):
    """Simple visual preview of how the pad layout will look on the device.

    This widget mirrors the 320x240 layout used by the ESP32 and scales it to
    fit the available space in the GUI while drawing rectangles for each
    button and its label.
    """

    button_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rects: list = []
        self._labels: dict[int, str] = {}
        self._screen_rect: tuple[float, float, float, float] | None = None
        self.setMinimumHeight(220)
        self.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 8px;
            }}
        """)

    def update_preview(self, button_count: int, labels_by_slot: dict[int, str]) -> None:
        """Recompute layout and trigger a repaint for the current page.

        button_count should be the number of active buttons on the current
        page; labels_by_slot maps 1-based slot numbers to label strings.
        """

        if button_count <= 0:
            self._rects = []
            self._labels = {}
        else:
            # Use the same layout generator as the firmware (320x240 screen).
            self._rects = generate_layout(button_count, 320, 240)
            self._labels = dict(labels_by_slot)

        self.update()

    def _compute_screen_rect(self) -> tuple[float, float, float, float]:
        available_width = max(float(self.width()) - 36.0, 1.0)
        available_height = max(float(self.height()) - 28.0, 1.0)
        aspect_ratio = 320.0 / 240.0

        if available_width / available_height > aspect_ratio:
            screen_height = available_height
            screen_width = screen_height * aspect_ratio
        else:
            screen_width = available_width
            screen_height = screen_width / aspect_ratio

        screen_x = (float(self.width()) - screen_width) / 2.0
        screen_y = (float(self.height()) - screen_height) / 2.0
        self._screen_rect = (screen_x, screen_y, screen_width, screen_height)
        return self._screen_rect

    def _button_palette(self) -> tuple[QColor, QColor, QColor, QColor, QColor, QColor]:
        base = QColor(CYBERPUNK_COLORS["neon_purple"])
        shell = base.darker(150)
        top = base.lighter(165)
        mid = base.lighter(125)
        bottom = base.darker(138)
        border = QColor(CYBERPUNK_COLORS["neon_cyan"])
        gloss = QColor(CYBERPUNK_COLORS["text_white"])
        return shell, top, mid, bottom, border, gloss

    def paintEvent(self, event):  # type: ignore[override]
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        body_x = 8
        body_y = 6
        body_w = max(1, self.width() - 16)
        body_h = max(1, self.height() - 12)
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        body_grad = QLinearGradient(body_x, body_y, body_x, body_y + body_h)
        body_grad.setColorAt(0.0, QColor("#0a0d14"))
        body_grad.setColorAt(0.5, QColor("#06080d"))
        body_grad.setColorAt(1.0, QColor("#030409"))
        painter.setBrush(QBrush(body_grad))
        painter.drawRoundedRect(body_x, body_y, body_w, body_h, 16, 16)
        body_border = QColor(CYBERPUNK_COLORS["neon_cyan"])
        body_border.setAlpha(48)
        painter.setPen(QPen(body_border, 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(body_x + 1, body_y + 1, body_w - 2, body_h - 2, 16, 16)

        screen_x, screen_y, screen_w, screen_h = self._compute_screen_rect()
        screen_grad = QLinearGradient(screen_x, screen_y, screen_x, screen_y + screen_h)
        screen_grad.setColorAt(0.0, QColor("#0a1420"))
        screen_grad.setColorAt(1.0, QColor("#071019"))
        screen_border = QColor(CYBERPUNK_COLORS["neon_purple"])
        screen_border.setAlpha(53)
        painter.setPen(QPen(screen_border, 1.1))
        painter.setBrush(QBrush(screen_grad))
        painter.drawRoundedRect(QRectF(screen_x, screen_y, screen_w, screen_h), 12.0, 12.0)

        if not self._rects:
            return

        base_w = 320.0
        base_h = 240.0
        scale_x = screen_w / base_w
        scale_y = screen_h / base_h

        pen = QPen(Qt.PenStyle.NoPen)
        painter.setPen(pen)

        shell, top, mid, bottom, border, gloss = self._button_palette()

        for rect in self._rects:
            x = int(screen_x + rect.x * scale_x)
            y = int(screen_y + rect.y * scale_y)
            bw = int(rect.w * scale_x)
            bh = int(rect.h * scale_y)

            if bw <= 8 or bh <= 8:
                continue

            radius = max(6.0, min(bw, bh) * 0.12)
            shadow_rect = (x + 3, y + 4, max(1, bw - 1), max(1, bh - 1))
            shadow_grad = QLinearGradient(shadow_rect[0], shadow_rect[1], shadow_rect[0], shadow_rect[1] + shadow_rect[3])
            shadow_grad.setColorAt(0.0, QColor(0, 0, 0, 90))
            shadow_grad.setColorAt(1.0, QColor(0, 0, 0, 165))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(shadow_grad))
            painter.drawRoundedRect(*shadow_rect, radius, radius)

            painter.setBrush(shell)
            painter.drawRoundedRect(x, y, bw, bh, radius, radius)

            face_x = x + 2
            face_y = y + 2
            face_w = max(1, bw - 4)
            face_h = max(1, bh - 4)
            face_radius = max(4.0, radius - 2.0)

            face_grad = QLinearGradient(face_x, face_y, face_x, face_y + face_h)
            face_grad.setColorAt(0.0, top)
            face_grad.setColorAt(0.45, mid)
            face_grad.setColorAt(1.0, bottom)
            painter.setBrush(QBrush(face_grad))
            painter.drawRoundedRect(face_x, face_y, face_w, face_h, face_radius, face_radius)

            gloss_w = max(10, face_w - 12)
            gloss_h = max(4, int(face_h * 0.18))
            gloss_grad = QLinearGradient(face_x, face_y + 3, face_x, face_y + 3 + gloss_h)
            gloss_top = QColor(gloss)
            gloss_top.setAlpha(80)
            gloss_bottom = QColor(gloss)
            gloss_bottom.setAlpha(8)
            gloss_grad.setColorAt(0.0, gloss_top)
            gloss_grad.setColorAt(1.0, gloss_bottom)
            painter.setBrush(QBrush(gloss_grad))
            painter.drawRoundedRect(face_x + 4, face_y + 3, gloss_w, gloss_h, gloss_h / 2, gloss_h / 2)

            painter.setPen(QPen(border, 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(x + 0.5, y + 0.5, bw - 1, bh - 1), radius, radius)

            inner_border = QColor(gloss)
            inner_border.setAlpha(110)
            painter.setPen(QPen(inner_border, 0.9))
            painter.drawRoundedRect(QRectF(face_x + 0.5, face_y + 0.5, face_w - 1, face_h - 1), face_radius, face_radius)

            painter.setPen(QPen(QColor(255, 255, 255, 65), 1.0))
            painter.drawLine(face_x + 5, face_y + 2, face_x + face_w - 6, face_y + 2)

            painter.setPen(QPen(QColor(0, 0, 0, 110), 1.0))
            painter.drawLine(face_x + 5, face_y + face_h - 3, face_x + face_w - 6, face_y + face_h - 3)

            label = self._labels.get(rect.slot, "")
            if label:
                font = painter.font()
                font.setBold(True)
                font.setPointSizeF(max(7.0, min(11.0, bh * 0.16)))
                painter.setFont(font)
                painter.setPen(QColor(0, 0, 0, 170))
                painter.drawText(
                    x + 1,
                    y + 1,
                    bw,
                    bh,
                    int(Qt.AlignmentFlag.AlignCenter),
                    label,
                )
                painter.setPen(QColor(CYBERPUNK_COLORS["text_white"]))
                painter.drawText(
                    x,
                    y,
                    bw,
                    bh,
                    int(Qt.AlignmentFlag.AlignCenter),
                    label,
                )

    def mousePressEvent(self, event):  # type: ignore[override]
        if not self._rects:
            return

        screen_x, screen_y, screen_w, screen_h = self._compute_screen_rect()
        if screen_w <= 0 or screen_h <= 0:
            return

        pos = event.position()
        x = pos.x()
        y = pos.y()
        if x < screen_x or x > screen_x + screen_w or y < screen_y or y > screen_y + screen_h:
            return

        base_w = 320.0
        base_h = 240.0
        scale_x = screen_w / base_w
        scale_y = screen_h / base_h
        lx = (x - screen_x) / scale_x
        ly = (y - screen_y) / scale_y

        for rect in self._rects:
            if lx >= rect.x and lx <= rect.x + rect.w and ly >= rect.y and ly <= rect.y + rect.h:
                self.button_clicked.emit(rect.slot)
                break


class TimeSettingsDialog(QDialog):
    """Dialog for selecting the server timezone used for pad time sync."""

    def __init__(self, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self.setWindowTitle("Time / Timezone Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Choose the timezone the DisplayPad Server should use\n"
            "when sending time to ESP32 devices. Default is CDT."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.combo = QComboBox()
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_settings()

    def _load_settings(self) -> None:
        url = f"http://127.0.0.1:{self.api_port}/api/v1/time/settings"
        try:
            resp = requests.get(url, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Time Settings",
                f"Failed to load time settings from API:\n{e}",
            )
            data = {
                "timezone": "America/Chicago",
                "available_timezones": ["America/Chicago"],
            }

        tz = data.get("timezone", "America/Chicago")
        zones = data.get("available_timezones") or ["America/Chicago"]

        self.combo.clear()
        self.combo.addItems(zones)

        idx = self.combo.findText(tz)
        if idx >= 0:
            self.combo.setCurrentIndex(idx)

    def on_accept(self) -> None:
        tz = self.combo.currentText().strip()
        url = f"http://127.0.0.1:{self.api_port}/api/v1/time/settings"
        try:
            resp = requests.put(url, json={"timezone": tz}, timeout=5)
            resp.raise_for_status()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Time Settings",
                f"Failed to save time settings to API:\n{e}",
            )
            return

        self.accept()
class PairingCodeDisplay(QFrame):
    """Widget to display the pairing code with countdown."""

    code_changed = pyqtSignal(str, int)

    def __init__(self, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self.current_code = ""
        self.expires_in = 0
        self.setup_ui()
        # Timers kept for compatibility but do nothing now; pairing codes removed.
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.refresh_code)
        self.update_timer.start(1000)
        self.countdown_timer = QTimer(self)
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.start(1000)

    def setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["neon_cyan"]}30,
                    stop: 1 {CYBERPUNK_COLORS["neon_cyan"]}10
                );
                border: 2px solid {CYBERPUNK_COLORS["neon_cyan"]};
                border-radius: 12px;
                padding: 10px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(15, 10, 15, 10)

        # Title
        self.label = QLabel("DISCOVERY STATUS")
        self.label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 10px; font-weight: bold;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)

        # Message
        self.code_label = QLabel(
            "ESP32 keypads now auto-discover this server.\n"
            "Connect a keypad to the same network and it will appear in the list."
        )
        self.code_label.setFont(QFont("Segoe UI", 10))
        self.code_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']}; padding: 5px;")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setWordWrap(True)
        layout.addWidget(self.code_label)

    def refresh_code(self):
        """No-op: pairing codes are no longer used."""
        return

    def update_countdown(self):
        """No-op: pairing codes are no longer used."""
        return

    def manual_rotate(self):
        """No-op: pairing codes are no longer used."""
        return


class PadListWidget(QFrame):
    """List of connected keypads."""

    pad_selected = pyqtSignal(dict)

    def __init__(self, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self.setup_ui()
        # Auto-refresh pads on startup and periodically so new/updated
        # devices appear without manual interaction.
        self.refresh_pads()
        self.refresh_timer = QTimer(self)
        self.refresh_timer.timeout.connect(self.refresh_pads)
        self.refresh_timer.start(3000)  # every 3 seconds

    def setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}35;
                border-radius: 16px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)

        # Header
        # Discovered Pads Section
        discovered_header = QLabel("DISCOVERED PADS")
        discovered_header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 11px; font-weight: bold; letter-spacing: 0.8px;")
        discovered_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(discovered_header)

        self.discovered_list = QListWidget()
        self.discovered_list.setMaximumHeight(140)
        self.discovered_list.setWordWrap(True)
        self.discovered_list.setStyleSheet(f"""
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_pink"]}35;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
            QListWidget::item {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_pink"]}25;
                border-radius: 10px;
                padding: 10px;
                margin: 3px 0px;
            }}
            QListWidget::item:hover {{
                background: {CYBERPUNK_COLORS["neon_pink"]}18;
            }}
        """)
        self.discovered_list.itemDoubleClicked.connect(self.add_discovered_pad)
        layout.addWidget(self.discovered_list)

        # Connected Keypads Section
        header = QLabel("CONNECTED KEYPADS")
        header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 12px; font-weight: bold; letter-spacing: 0.8px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}35;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
            QListWidget::item {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}40;
                border-radius: 12px;
                padding: 12px;
                margin: 4px 0px;
            }}
            QListWidget::item:hover {{
                background: {CYBERPUNK_COLORS["gothic_primary"]}18;
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
            QListWidget::item:selected {{
                background: {CYBERPUNK_COLORS["gothic_primary"]}22;
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
        """)
        self.list_widget.itemClicked.connect(self.on_pad_selected)
        layout.addWidget(self.list_widget)

        # Refresh button
        self.refresh_btn = CyberpunkButton("REFRESH", "green")
        self.refresh_btn.setFixedHeight(44)
        self.refresh_btn.clicked.connect(self.refresh_pads)
        layout.addWidget(self.refresh_btn)

    def refresh_pads(self):
        """Refresh the list of connected keypads."""
        try:
            response = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads",
                timeout=2
            )
            if response.status_code == 200:
                data = response.json()
                pads = data.get("pads", [])
                self.update_pad_list(pads)
        except Exception:
            pass
        # Also refresh discovered pads
        self.refresh_discovered()

    def update_pad_list(self, pads):
        """Update the list widget with pad data."""
        self.list_widget.clear()
        for pad in pads:
            item = QListWidgetItem()
            item.setText(f"📟 {pad.get('name', 'Unknown')}\n   ID: {pad.get('pad_uuid', 'N/A')[:16]}...")
            item.setData(Qt.ItemDataRole.UserRole, pad)
            item.setSizeHint(QSize(0, 62))
            self.list_widget.addItem(item)

    def on_pad_selected(self, item):
        """Handle pad selection."""
        pad_data = item.data(Qt.ItemDataRole.UserRole)
        self.pad_selected.emit(pad_data)

    def refresh_discovered(self):
        """Fetch discovered pads from API."""
        try:
            response = requests.get(f"http://127.0.0.1:{self.api_port}/api/v1/discovery/pads", timeout=2)
            if response.status_code == 200:
                discovered = response.json()
                self.update_discovered_list(discovered)
        except Exception:
            pass

    def update_discovered_list(self, discovered):
        """Update the discovered pads list."""
        self.discovered_list.clear()
        for pad in discovered:
            uuid_short = pad.get('uuid', 'Unknown')[:12]
            ip = pad.get('ip', 'Unknown')
            item_text = f"📡 {uuid_short}... @ {ip}\n   Touch: {pad.get('screen_width', 0)}x{pad.get('screen_height', 0)}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, pad)
            item.setSizeHint(QSize(0, 56))
            self.discovered_list.addItem(item)

    def add_discovered_pad(self, item):
        """Add a discovered pad to the system."""
        pad_data = item.data(Qt.ItemDataRole.UserRole)
        uuid = pad_data.get('uuid')
        if not uuid:
            return

        try:
            response = requests.post(
                f"http://127.0.0.1:{self.api_port}/api/v1/discovery/assign",
                json={"uuid": uuid, "name": f"Pad-{uuid[:8]}", "mode": "macro_keypad"},
                timeout=5
            )
            if response.status_code == 200:
                result = response.json()
                if result.get("success"):
                    # Refresh both lists
                    self.refresh_pads()
                    self.refresh_discovered()
        except Exception as e:
            print(f"[GUI] Failed to add pad: {e}")


class ButtonConfigWidget(QFrame):
    """Widget to configure a single button."""

    test_requested = pyqtSignal(int)

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._app_records: list | None = None
        self._pending_macro_action_id: str | None = None
        self._pending_icon_id: str | None = None
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 1 {CYBERPUNK_COLORS["bg_panel"]}
                );
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}55;
                border-radius: 16px;
                padding: 14px;
            }}
        """)

        self.setMinimumWidth(145)
        self.setMaximumWidth(285)
        self.setMinimumHeight(380)
        self.setMaximumHeight(380)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Slot label
        slot_label = QLabel(f"BUTTON {self.slot}")
        slot_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_purple']}; font-size: 11px; font-weight: bold; letter-spacing: 0.8px;")
        layout.addWidget(slot_label)

        # Label input
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Button Label")
        self.label_input.setStyleSheet(f"""
            QLineEdit {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}55;
                border-radius: 10px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 9px 10px;
                min-height: 20px;
            }}
        """)
        self.label_input.setClearButtonEnabled(True)
        self.label_input.setMaxLength(16)

        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_row.addWidget(self.label_input)

        self.show_text_checkbox = QCheckBox("Show text")
        self.show_text_checkbox.setChecked(True)
        self.show_text_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']}; font-size: 11px;")
        label_row.addWidget(self.show_text_checkbox)

        layout.addLayout(label_row)

        # Shared combo-box style for action/app/icon fields
        combo_style = f"""
            QComboBox {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}55;
                border-radius: 10px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 8px 10px;
                min-height: 20px;
            }}
            QComboBox QAbstractItemView {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                color: {CYBERPUNK_COLORS["text_white"]};
                selection-background-color: {CYBERPUNK_COLORS["gothic_primary"]}55;
            }}
        """

        # Action type
        self.action_type = QComboBox()
        self.action_type.addItems(["Macro", "Key Combo", "Mouse Click", "Application", "System Command"])
        self.action_type.setStyleSheet(combo_style)
        self.action_type.currentTextChanged.connect(self.on_action_type_changed)
        layout.addWidget(self.action_type)

        # Action details area: for most action types this is a free-form text
        # editor. For "Application" actions, we also expose an application
        # dropdown populated from the Application Library. For "Macro" actions,
        # a separate macro selection dropdown is shown instead so that only
        # predefined macros can be assigned to buttons.
        self.action_details = QTextEdit()
        self.action_details.setPlaceholderText("Action details (macro steps, key combo, etc.)")
        self.action_details.setMinimumHeight(96)
        self.action_details.setMaximumHeight(120)
        self.action_details.setStyleSheet(f"""
            QTextEdit {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}55;
                border-radius: 10px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 9px 10px;
            }}
        """)
        layout.addWidget(self.action_details)

        # Macro selector (initially hidden). When the action type is
        # "Macro", we show this combo box instead of the free-form
        # action_details editor.
        self.macro_combo = QComboBox()
        self.macro_combo.setStyleSheet(combo_style)
        self.macro_combo.setVisible(False)
        layout.addWidget(self.macro_combo)

        # Application selector (initially hidden). When the action type is
        # "Application", we show this combo box instead of the free-form
        # action_details editor.
        self.app_combo = QComboBox()
        self.app_combo.setEditable(True)
        self.app_combo.setStyleSheet(combo_style)
        self.app_combo.setVisible(False)
        layout.addWidget(self.app_combo)

        # Icon selection (will be populated by parent dialog with real icon_ids)
        icon_row = QHBoxLayout()
        self.icon_combo = QComboBox()
        # Provide a minimal default; KeypadConfigDialog will overwrite items.
        self.icon_combo.addItems(["None"])
        self.icon_combo.setStyleSheet(combo_style)
        icon_row.addWidget(self.icon_combo)

        # For application actions with an imported icon, this checkbox allows
        # the user to override the application icon with a normal macro icon.
        self.override_app_icon_checkbox = QCheckBox("Override app icon")
        self.override_app_icon_checkbox.setVisible(False)
        self.override_app_icon_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 11px;")
        self.override_app_icon_checkbox.stateChanged.connect(
            lambda _state: self._update_icon_field_state()
        )
        icon_row.addWidget(self.override_app_icon_checkbox)

        layout.addLayout(icon_row)

        # Track application records for the "Application" action type and
        # manage whether the icon field should use the application icon.
        self._app_records: list = []
        self._app_icon_label = "Using Application Icon"
        self.app_combo.currentIndexChanged.connect(self._on_app_selection_changed)

        color_row = QHBoxLayout()

        # Small swatch-style buttons that open a color dialog; they display the
        # current color and store it as a #RRGGBB string internally.
        self.bg_color_btn = QPushButton("Background")
        self.bg_color_btn.clicked.connect(lambda: self.pick_color("bg"))
        color_row.addWidget(self.bg_color_btn)

        self.icon_color_btn = QPushButton("Icon")
        self.icon_color_btn.clicked.connect(lambda: self.pick_color("icon"))
        color_row.addWidget(self.icon_color_btn)

        self.text_color_btn = QPushButton("Text")
        self.text_color_btn.clicked.connect(lambda: self.pick_color("text"))
        color_row.addWidget(self.text_color_btn)

        for color_btn in (self.bg_color_btn, self.icon_color_btn, self.text_color_btn):
            color_btn.setMinimumHeight(32)

        layout.addLayout(color_row)

        # Lightweight "Test" button so users can trigger this slot on the
        # currently connected pad from the GUI without needing to press the
        # physical device.
        test_row = QHBoxLayout()
        test_row.addStretch()
        self.test_btn = QPushButton("Test Button")
        self.test_btn.setFixedHeight(32)
        self.test_btn.clicked.connect(self._on_test_clicked)
        test_row.addWidget(self.test_btn)
        layout.addLayout(test_row)

        # Internal storage for colors as hex strings (e.g. "#RRGGBB").
        # Defaults: BG=Purple (neon_purple), Icon=Black (#000000), Text=White (#FFFFFF)
        self._bg_color_hex: str | None = CYBERPUNK_COLORS["neon_purple"]
        self._icon_color_hex: str | None = "#000000"
        self._text_color_hex: str | None = "#FFFFFF"

        # Apply defaults to the swatch buttons
        self._update_color_button(self.bg_color_btn, self._bg_color_hex)
        self._update_color_button(self.icon_color_btn, self._icon_color_hex)
        self._update_color_button(self.text_color_btn, self._text_color_hex)

        # Initialize the action-specific UI (Macro / Application / other)
        # based on the default action type selection so that, for example,
        # when "Macro" is selected the macro dropdown is shown instead of
        # the free-form keystroke text box.
        self.on_action_type_changed(self.action_type.currentText())

    def _on_test_clicked(self) -> None:
        """Emit a signal so the parent dialog can test this slot on the pad."""

        self.test_requested.emit(self.slot)

    @staticmethod
    def _quantize_color_for_esp32(color: "QColor") -> str:
        """Quantize a QColor to the ESP32's RGB565 palette and return #RRGGBB.

        This snaps the 8-bit channels to the nearest values the device will
        actually show, so what you pick in the GUI matches more closely what
        appears on the DisplayPad.
        """
        r = color.red()
        g = color.green()
        b = color.blue()

        # Quantize to 5/6/5 bits then expand back to 8-bit for display.
        r5 = (r + 4) // 8
        g6 = (g + 2) // 4
        b5 = (b + 4) // 8

        r8 = (r5 * 255) // 31
        g8 = (g6 * 255) // 63
        b8 = (b5 * 255) // 31

        return f"#{r8:02X}{g8:02X}{b8:02X}"

    def on_action_type_changed(self, action_type):
        """Update placeholder based on action type."""
        placeholders = {
            # For Macro actions, macros are designed in Macro Designer and
            # selected using the dropdown below, not typed here.
            "Macro": "Select a macro from the dropdown below (defined in Macro Designer)",
            "Key Combo": "Enter key combination:\nctrl+alt+delete\nctrl+c\nctrl+v",
            "Mouse Click": "Enter click details:\nLEFT 100 200\nRIGHT 300 400",
            # For Application, the real UI will be a dropdown backed by the
            # Application Library; keep a simple hint here for now.
            "Application": "Select an application from the library (coming soon)",
            "System Command": "Enter command:\nshutdown /s /t 0\nnotepad.exe",
        }
        self.action_details.setPlaceholderText(placeholders.get(action_type, "Enter action details"))

        # Toggle between free-form text editor, macro dropdown, and
        # application dropdown depending on action type.
        if action_type == "Application":
            previous_app_id = self.app_combo.currentData() if self.app_combo.count() > 0 else None
            previous_app_text = self.app_combo.currentText().strip() if self.app_combo.currentText() else ""
            self.action_details.setVisible(False)
            self.macro_combo.setVisible(False)
            self.app_combo.setVisible(True)

            # Populate application list from the Application Library
            try:
                from displaypad_server import applications as app_repo

                apps = app_repo.list_applications(enabled_only=True)
            except Exception as e:  # pragma: no cover - best-effort logging
                print(f"[GUI] Failed to load applications: {e}", flush=True)
                apps = []

            self._app_records = list(apps)
            self.app_combo.blockSignals(True)
            self.app_combo.clear()
            if not apps:
                self.app_combo.addItem("(No applications in library)", None)
            else:
                for app in apps:
                    # Store app id in userData for lookup later
                    self.app_combo.addItem(app.name, app.id)

            if previous_app_id is not None:
                idx = self.app_combo.findData(previous_app_id)
                if idx >= 0:
                    self.app_combo.setCurrentIndex(idx)
            elif previous_app_text:
                idx = self.app_combo.findText(previous_app_text, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.app_combo.setCurrentIndex(idx)
            self.app_combo.blockSignals(False)
            # Configure completer for case-insensitive popup completion
            completer = self.app_combo.completer()
            if isinstance(completer, QCompleter):
                completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
                completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        elif action_type == "Macro":
            # For Macro actions we only allow selecting from predefined
            # macros; free-form text is hidden.
            self.app_combo.setVisible(False)
            self.action_details.setVisible(False)
            self.macro_combo.setVisible(True)
        else:
            self.app_combo.setVisible(False)
            self.macro_combo.setVisible(False)
            self.action_details.setVisible(True)

        # Update icon field state based on current action/app selection
        self._update_icon_field_state()

    def _on_app_selection_changed(self, index: int) -> None:
        # When the selected application changes, re-evaluate whether we should
        # use its imported icon or allow manual icon selection.
        self._update_icon_field_state()

    def _application_has_imported_icon(self, app_id: int | None) -> bool:
        if app_id is None:
            return False
        try:
            from displaypad_server import application_icons as app_icons_repo

            record = app_icons_repo.get_primary_icon_for_application(app_id)
            return record is not None
        except Exception:
            # If anything goes wrong, fall back to allowing manual icons.
            return False

    def _ensure_app_icon_label_item(self) -> None:
        """Ensure the special "Using Application Icon" entry exists."""

        if self.icon_combo.findText(self._app_icon_label) < 0:
            self.icon_combo.insertItem(0, self._app_icon_label)

    def _update_icon_field_state(self) -> None:
        """Enable/disable the icon field based on action + app icon presence."""

        action_type = self.action_type.currentText()
        has_app_icon = False
        if action_type == "Application":
            # Determine whether the selected application has an imported icon.
            app_id = self.app_combo.currentData()
            has_app_icon = self._application_has_imported_icon(app_id)

        # Show or hide the override checkbox based on whether there is an
        # application icon to override.
        self.override_app_icon_checkbox.setVisible(action_type == "Application" and has_app_icon)

        # If this is an Application action with an imported icon and the user
        # has NOT chosen to override, lock the icon combo to the special
        # "Using Application Icon" entry.
        if action_type == "Application" and has_app_icon and not self.override_app_icon_checkbox.isChecked():
            self._ensure_app_icon_label_item()
            idx = self.icon_combo.findText(self._app_icon_label)
            if idx >= 0:
                self.icon_combo.setCurrentIndex(idx)
            self.icon_combo.setEnabled(False)
            return

        # For non-Application actions, Application without an imported icon,
        # or when override is enabled, allow manual icon selection as normal.
        self.icon_combo.setEnabled(True)
        # If we were previously in "Using Application Icon" mode, snap back to
        # a neutral selection such as "None" when manual icons are allowed.
        if self.icon_combo.currentText() == self._app_icon_label:
            idx = self.icon_combo.findText("None")
            if idx >= 0:
                self.icon_combo.setCurrentIndex(idx)

    def get_config(self) -> dict:
        """Get the button configuration."""
        icon_text = self.icon_combo.currentText()
        # Treat "None" as no icon so firmware does not request None.png.
        # Also treat the special "Using Application Icon" label as meaning the
        # button should rely on the associated application's icon rather than
        # a monochrome firmware icon.
        if icon_text in ("None", self._app_icon_label):
            icon_id = ""
        else:
            icon_id = icon_text
        cfg = {
            "slot": self.slot,
            "label": self.label_input.text() or f"Button {self.slot}",
            "icon": icon_id,
            "action_type": self.action_type.currentText(),
            "action_details": self.action_details.toPlainText(),
            # Colors are stored as #RRGGBB strings in the config/DB.
            "bg_color": self._bg_color_hex,
            "icon_color": self._icon_color_hex,
            "text_color": self._text_color_hex,
            "show_text": self.show_text_checkbox.isChecked(),
        }
        # If this is a Macro action, attach the selected macro_action_id so the
        # server can resolve it via the macros table.
        if cfg["action_type"] == "Macro":
            macro_action_id = self.macro_combo.currentData()
            if isinstance(macro_action_id, str) and macro_action_id:
                cfg["macro_action_id"] = macro_action_id

        # If this is a Launch Application action, attach snapshot fields from
        # the selected application record so the host can launch directly from
        # the button config without re-querying the library.
        if cfg["action_type"] == "Application" and self._app_records:
            app_id = self.app_combo.currentData()
            selected = None
            for rec in self._app_records:
                if rec.id == app_id:
                    selected = rec
                    break

            if selected is not None:
                cfg.update(
                    {
                        "application_id": selected.id,
                        "application_name": selected.name,
                        "executable_path": selected.executable_path,
                        "working_directory": selected.working_directory,
                        "arguments": selected.arguments,
                        # Default to not overriding args at button-level yet
                        "override_arguments": None,
                        "icon_path": selected.icon_path,
                        # Run mode placeholder; can be extended later
                        "run_mode": "normal",
                        "launch_source_snapshot_time": datetime.now(timezone.utc).isoformat(),
                        "source": selected.detection_source or ("manual" if selected.is_manual else "library"),
                    }
                )

        return cfg

    def set_config(self, cfg: dict) -> None:
        """Populate widget from an existing button config dict."""
        if not cfg:
            return

        label = cfg.get("label") or ""
        icon_id = cfg.get("icon_id") or ""
        action_type = cfg.get("action_type") or ""
        action_details = cfg.get("action_details") or ""
        show_text = cfg.get("show_text")
        bg_color = cfg.get("bg_color")
        icon_color = cfg.get("icon_color")
        text_color = cfg.get("text_color")

        if label:
            self.label_input.setText(label)

        if show_text is None:
            self.show_text_checkbox.setChecked(True)
        else:
            self.show_text_checkbox.setChecked(bool(show_text))

        if action_type:
            idx = self.action_type.findText(action_type, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.action_type.setCurrentIndex(idx)

        if action_details:
            self.action_details.setPlainText(action_details)

        # For Application actions, attempt to pre-select the matching
        # application in the dropdown based on application_id or
        # application_name from the config.
        if action_type == "Application":
            application_id = cfg.get("application_id")
            application_name = cfg.get("application_name")

            # Ensure combo is populated
            self.on_action_type_changed("Application")

            if application_id is not None:
                idx = self.app_combo.findData(application_id)
                if idx >= 0:
                    self.app_combo.setCurrentIndex(idx)
            elif application_name:
                idx = self.app_combo.findText(application_name, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.app_combo.setCurrentIndex(idx)

            # Restore override checkbox state: if this Application button has
            # an application_id and a non-empty icon_id, treat that as an
            # explicit override of the application icon.
            has_icon_override = bool(application_id is not None and icon_id)
            self.override_app_icon_checkbox.setChecked(has_icon_override)

        # After we have restored the action type, application selection, and
        # override state, re-apply the saved macro icon selection if present.
        # This ensures that Application buttons with "Override app icon"
        # enabled keep their chosen macro icon instead of reverting back to a
        # default when the dialog is reopened.
        self._pending_icon_id = str(icon_id) if isinstance(icon_id, str) and icon_id else None
        if icon_id:
            idx = self.icon_combo.findText(icon_id, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.icon_combo.setCurrentIndex(idx)
                self._pending_icon_id = None

        # Initialize internal hex storage and button appearance. If a given
        # color is not present in the config, keep the existing default.
        if isinstance(bg_color, str):
            self._bg_color_hex = bg_color
        if isinstance(icon_color, str):
            self._icon_color_hex = icon_color
        if isinstance(text_color, str):
            self._text_color_hex = text_color

        self._update_color_button(self.bg_color_btn, self._bg_color_hex)
        self._update_color_button(self.icon_color_btn, self._icon_color_hex)
        self._update_color_button(self.text_color_btn, self._text_color_hex)

        # For Macro actions, attempt to restore the selected macro in the
        # dropdown based on macro_action_id from the config.
        if action_type == "Macro":
            macro_action_id = cfg.get("macro_action_id")
            self._pending_macro_action_id = str(macro_action_id) if isinstance(macro_action_id, str) and macro_action_id else None
            if macro_action_id is not None:
                idx = self.macro_combo.findData(macro_action_id)
                if idx >= 0:
                    self.macro_combo.setCurrentIndex(idx)
                    self._pending_macro_action_id = None

        # Ensure the icon field reflects the current action/app selection
        self._update_icon_field_state()

    def _update_color_button(self, btn: QPushButton, hex_color: str | None) -> None:
        """Apply background to a color button based on a #RRGGBB string."""
        if hex_color and isinstance(hex_color, str):
            btn.setText("")
            btn.setStyleSheet(
                f"QPushButton {{ background: {hex_color}; border: 1px solid {CYBERPUNK_COLORS['neon_cyan']}; }}"
            )
        else:
            # No color set: show label text and default style
            btn.setStyleSheet(self.label_input.styleSheet())

    def pick_color(self, which: str) -> None:
        """Open a color dialog and update the chosen color button/state."""
        current_hex = None
        if which == "bg":
            current_hex = self._bg_color_hex
        elif which == "icon":
            current_hex = self._icon_color_hex
        elif which == "text":
            current_hex = self._text_color_hex

        initial = QColor(current_hex) if current_hex else QColor("#ffffff")
        color = QColorDialog.getColor(initial, self, "Select Color")
        if not color.isValid():
            return

        # Snap the chosen color to the ESP32's RGB565 palette so the value we
        # save and display in the GUI matches what the device can render.
        hex_str = self._quantize_color_for_esp32(color)
        if which == "bg":
            self._bg_color_hex = hex_str
            self._update_color_button(self.bg_color_btn, hex_str)
        elif which == "icon":
            self._icon_color_hex = hex_str
            self._update_color_button(self.icon_color_btn, hex_str)
        elif which == "text":
            self._text_color_hex = hex_str
            self._update_color_button(self.text_color_btn, hex_str)


class KeypadConfigDialog(QDialog):
    """Dialog for configuring a keypad."""

    def __init__(self, pad_data: dict, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.pad_data = pad_data
        self.api_port = api_port
        self.button_configs = []
        self.available_icons: list[str] = []
        self.layout_profiles: list[dict] = []
        self.active_layout_profile: str | None = None
        self._syncing_profile_combo = False
        self.control_panel_policy: dict = {}
        self._pending_relayout = False
        self.setWindowTitle(f"Configure Keypad - {pad_data.get('name', 'Unknown')}")
        # Ensure there is enough horizontal space for 4 button tiles (275px each)
        # plus spacing and margins. Slightly enlarged for more breathing room.
        self.setMinimumSize(1240, 800)
        screen = QApplication.primaryScreen()
        if screen is not None:
            geom = screen.availableGeometry()
            left = geom.left() + 5
            top = geom.top() + 5
            width = max(self.minimumWidth(), geom.width() - 10)
            height = max(self.minimumHeight(), geom.height() - 10)
            self.setGeometry(left, top, width, height)
        self.setup_ui()
        self.apply_cyberpunk_theme()

        self.preview_dialog = QDialog(self)
        self.preview_dialog.setWindowTitle("Keypad Preview")
        pv_layout = QVBoxLayout(self.preview_dialog)
        pv_layout.setContentsMargins(0, 0, 0, 0)
        pv_layout.setSpacing(0)

        chrome_frame = QFrame(self.preview_dialog)
        chrome_frame.setObjectName("previewChrome")
        chrome_frame.setFixedHeight(34)
        chrome_frame.setStyleSheet(
            f"QFrame#previewChrome {{ background: #0b4fa8; border-bottom: 1px solid {CYBERPUNK_COLORS['neon_cyan']}; }}"
        )
        chrome_layout = QHBoxLayout(chrome_frame)
        chrome_layout.setContentsMargins(8, 4, 8, 4)
        chrome_layout.setSpacing(6)

        preview_name = self.pad_data.get("name", "Unknown Pad")
        self.preview_time_label = QLabel()
        self.preview_time_label.setStyleSheet(
            f"background: transparent; color: {CYBERPUNK_COLORS['text_white']}; font-weight: bold;"
        )
        self.preview_time_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        chrome_layout.addWidget(self.preview_time_label, 1)

        self.preview_menu_label = QLabel(preview_name)
        self.preview_menu_label.setStyleSheet(
            f"background: transparent; color: {CYBERPUNK_COLORS['text_white']}; font-weight: bold;"
        )
        self.preview_menu_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chrome_layout.addWidget(self.preview_menu_label, 2)

        chrome_right_widget = QWidget(chrome_frame)
        chrome_right_widget.setStyleSheet("background: transparent;")
        chrome_right_layout = QHBoxLayout(chrome_right_widget)
        chrome_right_layout.setContentsMargins(0, 0, 0, 0)
        chrome_right_layout.setSpacing(6)

        self.preview_status_light_green = QLabel()
        self.preview_status_light_green.setFixedSize(10, 10)
        self.preview_status_light_green.setStyleSheet(
            f"background: {CYBERPUNK_COLORS['neon_green']}; border-radius: 5px;"
        )
        chrome_right_layout.addWidget(self.preview_status_light_green)

        self.preview_status_light_blue = QLabel()
        self.preview_status_light_blue.setFixedSize(10, 10)
        self.preview_status_light_blue.setStyleSheet(
            f"background: {CYBERPUNK_COLORS['neon_cyan']}; border-radius: 5px;"
        )
        chrome_right_layout.addWidget(self.preview_status_light_blue)

        self.preview_control_panel_btn = QPushButton("⚙")
        self.preview_control_panel_btn.setFlat(True)
        self.preview_control_panel_btn.setFixedSize(18, 18)
        self.preview_control_panel_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none; color: {CYBERPUNK_COLORS['text_white']}; padding: 0px; margin: 0px; font-size: 16px; }} "
            f"QPushButton:hover {{ background: transparent; border: none; color: {CYBERPUNK_COLORS['neon_cyan']}; }}"
        )
        self.preview_control_panel_btn.clicked.connect(self._show_fake_control_panel)
        chrome_right_layout.addWidget(self.preview_control_panel_btn)

        chrome_layout.addWidget(chrome_right_widget, 1)

        pv_layout.addWidget(chrome_frame)

        self.preview_widget = PadPreviewWidget(self.preview_dialog)
        pv_layout.addWidget(self.preview_widget)
        self.preview_dialog.resize(460, 360)
        self.preview_widget.button_clicked.connect(
            lambda slot: self._on_button_test_requested(self.current_page, slot)
        )
        self.preview_clock_timer = QTimer(self)
        self.preview_clock_timer.setInterval(1000)
        self.preview_clock_timer.timeout.connect(self._update_preview_clock)
        self.preview_clock_timer.start()
        self._update_preview_clock()
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(0)
        self._relayout_timer.timeout.connect(self._run_pending_relayout)
        self.preview_dialog.show()

        # Create a hidden session watcher so pads can react to Windows
        # lock/unlock even when the main window is minimized.
        if sys.platform == "win32":
            try:
                self._session_watcher = SessionStateWatcher(self.api_port, parent=self)
            except Exception:
                self._session_watcher = None
        self._load_icon_list()
        self._load_macro_list()
        # Automatically refresh macros when the Macro Builder broadcasts changes.
        try:
            MACRO_EVENT_BUS.macros_changed.connect(self.refresh_macros)
        except Exception:
            pass
        self.load_existing_config()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QLabel(f"KEYPAD CONFIGURATION")
        header.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; padding: 10px;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # Pad info
        info_frame = QFrame()
        info_frame.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 8px;
                padding: 10px;
            }}
        """)
        info_layout = QGridLayout(info_frame)
        info_layout.addWidget(QLabel(f"ID: {self.pad_data.get('pad_uuid', 'N/A')}"), 0, 0)
        info_layout.addWidget(QLabel(f"Mode: {self.pad_data.get('mode', 'button_pad')}"), 0, 1)
        layout.addWidget(info_frame)

        profile_frame = QFrame()
        profile_layout = QHBoxLayout(profile_frame)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(10)
        profile_layout.addWidget(QLabel("Layout Profile:"))

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(240)
        self.profile_combo.currentTextChanged.connect(self._on_profile_changed)
        profile_layout.addWidget(self.profile_combo)

        self.new_profile_btn = QPushButton("New Profile")
        self.new_profile_btn.setFixedHeight(28)
        self.new_profile_btn.clicked.connect(self._create_layout_profile)
        profile_layout.addWidget(self.new_profile_btn)

        self.save_profile_btn = QPushButton("Update Profile")
        self.save_profile_btn.setFixedHeight(28)
        self.save_profile_btn.clicked.connect(self._save_layout_profile)
        profile_layout.addWidget(self.save_profile_btn)

        self.rename_profile_btn = QPushButton("Rename")
        self.rename_profile_btn.setFixedHeight(28)
        self.rename_profile_btn.clicked.connect(self._rename_layout_profile)
        profile_layout.addWidget(self.rename_profile_btn)

        self.delete_profile_btn = QPushButton("Delete")
        self.delete_profile_btn.setFixedHeight(28)
        self.delete_profile_btn.clicked.connect(self._delete_layout_profile)
        profile_layout.addWidget(self.delete_profile_btn)
        profile_layout.addStretch()
        layout.addWidget(profile_frame)

        # Keypad Type Selection (mutually-exclusive radios: Task vs Macro)
        type_frame = QFrame()
        type_layout = QHBoxLayout(type_frame)
        type_layout.setSpacing(15)

        self.task_radio = QRadioButton("Task Keypad")
        self.task_radio.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_yellow']}; font-size: 14px;")

        self.macro_radio = QRadioButton("Macro Keypad")
        self.macro_radio.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 14px;")

        # Group them so only one can be active at a time.
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.task_radio)
        self.mode_group.addButton(self.macro_radio)

        # Default to Macro Keypad since the current button design is for macros.
        self.macro_radio.setChecked(True)

        # React to mode changes so we can adjust button configuration UI
        # between Task Keypad (favorite apps) and Macro Keypad (rich actions).
        self.task_radio.toggled.connect(self._on_mode_changed)
        self.macro_radio.toggled.connect(self._on_mode_changed)

        type_layout.addWidget(QLabel("Keypad Type:"))
        type_layout.addWidget(self.task_radio)
        type_layout.addWidget(self.macro_radio)

        # Button count selector (per-page; value depends on active page)
        type_layout.addSpacing(30)
        type_layout.addWidget(QLabel("Buttons on this page:"))
        self.button_count_combo = QComboBox()
        self.button_count_combo.addItems(["6", "8", "10", "12", "16", "20", "24", "28", "32"])
        self.button_count_combo.setCurrentText("6")
        self.button_count_combo.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        # Per-page button counts; default page 1 -> 6 buttons
        self.page_button_counts: dict[int, int] = {1: 6}
        self.button_count_combo.currentTextChanged.connect(self._on_button_count_changed)
        type_layout.addWidget(self.button_count_combo)

        # Time configuration
        type_layout.addSpacing(30)
        type_layout.addWidget(QLabel("Time format:"))
        self.time_format_combo = QComboBox()
        self.time_format_combo.addItems(["12-hour", "24-hour"])
        self.time_format_combo.setCurrentIndex(0)
        self.time_format_combo.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.time_format_combo.currentIndexChanged.connect(lambda _index: self._update_preview_clock())
        type_layout.addWidget(self.time_format_combo)

        self.ampm_checkbox = QCheckBox("Show AM/PM")
        self.ampm_checkbox.setChecked(True)
        self.ampm_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.ampm_checkbox.toggled.connect(lambda _checked: self._update_preview_clock())
        type_layout.addWidget(self.ampm_checkbox)

        # Host lock behavior
        type_layout.addSpacing(10)
        self.blank_on_lock_checkbox = QCheckBox("Blank screen when host is locked")
        self.blank_on_lock_checkbox.setChecked(True)
        self.blank_on_lock_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        type_layout.addWidget(self.blank_on_lock_checkbox)

        type_layout.addStretch()
        layout.addWidget(type_frame)

        # Buttons configuration
        buttons_label = QLabel("BUTTON CONFIGURATION")
        buttons_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_purple']}; font-size: 12px; font-weight: bold;")
        layout.addWidget(buttons_label)

        # Page selector + scroll area for buttons
        page_bar = QHBoxLayout()

        # Total page count selector
        page_bar.addWidget(QLabel("Pages:"))
        self.page_count_combo = QComboBox()
        self.page_count_combo.addItems(["1", "2", "3", "4"])
        self.page_count_combo.setCurrentIndex(0)
        self.page_count_combo.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.page_count_combo.currentIndexChanged.connect(self._on_page_count_changed)
        page_bar.addWidget(self.page_count_combo)

        page_bar.addSpacing(20)

        page_bar.addWidget(QLabel("Page:"))
        self.page_combo = QComboBox()
        self.page_combo.addItems(["1"])  # will be expanded by page_count_combo
        self.page_combo.setCurrentIndex(0)
        self.page_combo.currentIndexChanged.connect(self._on_page_changed)
        page_bar.addWidget(self.page_combo)
        # Allow reloading macros without closing the dialog.
        self.refresh_macros_btn = QPushButton("Refresh Macros")
        self.refresh_macros_btn.setFixedHeight(28)
        self.refresh_macros_btn.clicked.connect(self.refresh_macros)
        page_bar.addSpacing(10)
        page_bar.addWidget(self.refresh_macros_btn)
        page_bar.addStretch()
        layout.addLayout(page_bar)

        # Scroll area for buttons on the current page
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background: {CYBERPUNK_COLORS["bg_dark"]};
            }}
            QScrollBar:vertical {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                width: 12px;
            }}
            QScrollBar::handle:vertical {{
                background: {CYBERPUNK_COLORS["neon_cyan"]};
                border-radius: 6px;
            }}
        """)
        self.scroll_area.viewport().installEventFilter(self)

        self.buttons_container = QWidget()
        self.buttons_grid = QGridLayout(self.buttons_container)
        # More generous spacing between tiles for readability on large layouts.
        self.buttons_grid.setHorizontalSpacing(10)
        self.buttons_grid.setVerticalSpacing(12)
        self.buttons_grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        # Keep all widgets for all pages, but show only the current page
        self.all_button_widgets: dict[int, list[ButtonConfigWidget]] = {}
        self.current_page = 1
        # Initially create a default of 6 button configs on page 1; load_existing_config
        # may later resize this up to the actual button count (max 32).
        self._create_button_widgets(self.page_button_counts.get(1, 6))

        self.scroll_area.setWidget(self.buttons_container)
        layout.addWidget(self.scroll_area, 1)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.save_config)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_button_widgets(self, count: int) -> None:
        """Create ButtonConfigWidgets for the current page (up to 32 per page)."""
        # Clamp to 1-32
        count = max(1, min(32, count))

        # Remove existing widgets from the grid (they remain in all_button_widgets)
        while self.buttons_grid.count():
            item = self.buttons_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        # Get or create list for this page
        page = self.current_page
        if page not in self.all_button_widgets:
            self.all_button_widgets[page] = []

        page_widgets = self.all_button_widgets[page]

        # Ensure we have the right number of widgets for this page
        while len(page_widgets) < count:
            slot = len(page_widgets) + 1
            w = ButtonConfigWidget(slot)
            w.test_requested.connect(lambda s=slot, p=page: self._on_button_test_requested(p, s))
            w.label_input.textChanged.connect(lambda _text, p=page: self._update_preview_for_current_page())
            page_widgets.append(w)

        self.button_configs = page_widgets[:count]

        self._schedule_relayout_buttons()
        self._update_preview_for_current_page()

    def _on_button_count_changed(self, text: str) -> None:
        """Update button count for the current page and rebuild its widgets."""
        try:
            count = int(text)
        except ValueError:
            return

        page = self.current_page
        self.page_button_counts[page] = count
        self._create_button_widgets(count)
        self._update_preview_for_current_page()

    def _relayout_buttons(self) -> None:
        if not hasattr(self, "button_configs") or not self.button_configs:
            return

        while self.buttons_grid.count():
            item = self.buttons_grid.takeAt(0)
            # Do not change widget parent; widgets remain owned by buttons_container

        spacing = 3

        if hasattr(self, "scroll_area") and self.scroll_area is not None:
            available_width = self.scroll_area.viewport().width()
        else:
            available_width = self.width()

        if available_width <= 0:
            available_width = self.width()

        target_cols = min(6, len(self.button_configs))
        usable_width = max(available_width - 12, 0)
        tile_width = max(145, min(285, (usable_width - max(0, target_cols - 1) * spacing) // max(1, target_cols)))
        max_cols_by_width = max(1, (usable_width + spacing) // (tile_width + spacing))
        cols = max(1, min(target_cols, max_cols_by_width))
        tile_width = max(145, min(285, (usable_width - max(0, cols - 1) * spacing) // max(1, cols)))

        for i, btn_config in enumerate(self.button_configs):
            btn_config.setFixedWidth(tile_width)
            self._populate_icon_combo(btn_config)
            self._populate_macro_combo(btn_config)
            row = i // cols
            col = i % cols
            self.buttons_grid.addWidget(btn_config, row, col)

        # Ensure the per-button UI matches the current keypad mode
        self._apply_mode_to_button_widgets()

    def _on_button_test_requested(self, page: int, slot_on_page: int) -> None:
        pad_uuid = self.pad_data.get("pad_uuid")
        if not pad_uuid:
            QMessageBox.warning(self, "Test Button", "Pad ID is not available for testing.")
            return

        total_pages = self.page_count_combo.currentIndex() + 1
        page_counts: list[int] = []
        for p in range(1, total_pages + 1):
            count = self.page_button_counts.get(p)
            if count is None:
                try:
                    count = int(self.button_count_combo.currentText())
                except ValueError:
                    count = 6
            page_counts.append(max(1, min(32, int(count))))

        if page < 1 or page > len(page_counts):
            return

        per_page_limit = page_counts[page - 1]
        local_slot = max(1, min(per_page_limit, int(slot_on_page)))
        offset = sum(page_counts[: page - 1])
        global_slot = offset + local_slot

        try:
            resp = requests.post(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads/{pad_uuid}/press",
                json={"slot": global_slot, "press_type": "tap"},
                timeout=5,
            )
            if resp.status_code != 200:
                QMessageBox.warning(self, "Test Button", f"Test failed: {resp.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Test Button", f"Network error during test:\n{e}")

    def _apply_mode_to_button_widgets(self) -> None:
        """Adjust button widget behavior for Task vs Macro keypad modes.

        - Task Keypad: each button is a favorite application slot. We lock the
          action type to "Application" and show only the application selector
          (plus label and icon choices).
        - Macro Keypad: full action-type selection is available (Macro,
          Application, Key Combo, Mouse Click, System Command).
        """

        is_task_mode = getattr(self, "task_radio", None) is not None and self.task_radio.isChecked()

        for widgets in self.all_button_widgets.values():
            for btn in widgets:
                # In Task mode, fix the action type to Application and disable
                # the action-type selector so the user only picks which app
                # this button watches/launches.
                if is_task_mode:
                    idx = btn.action_type.findText("Application", Qt.MatchFlag.MatchFixedString)
                    if idx >= 0:
                        btn.action_type.setCurrentIndex(idx)
                    btn.action_type.setEnabled(False)
                    # Ensure the UI reflects Application mode (shows app combo)
                    btn.on_action_type_changed("Application")
                else:
                    # In Macro mode, allow full configuration again.
                    btn.action_type.setEnabled(True)
                    # on_action_type_changed is already wired to the combo
                    # via currentTextChanged; no need to force a specific mode.

    def _on_mode_changed(self, _checked: bool) -> None:
        """Handle changes between Task and Macro keypad modes."""

        self._apply_mode_to_button_widgets()

    def _on_page_changed(self, index: int) -> None:
        """Switch the visible page in the editor."""
        self.current_page = index + 1

        # Determine the button count for this page (default to 6 if unseen)
        count = self.page_button_counts.get(self.current_page)
        if count is None:
            try:
                count = int(self.button_count_combo.currentText())
            except ValueError:
                count = 6
            self.page_button_counts[self.current_page] = count

        # Sync the combo box without re-triggering the handler
        self.button_count_combo.blockSignals(True)
        self.button_count_combo.setCurrentText(str(count))
        self.button_count_combo.blockSignals(False)

        # Recreate widgets for this page using its button count
        self._create_button_widgets(count)
        self._update_preview_for_current_page()

    def _on_page_count_changed(self, index: int) -> None:
        """Update the total number of pages for this pad."""
        total_pages = index + 1

        # Rebuild page selector items to match total_pages
        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for p in range(1, total_pages + 1):
            self.page_combo.addItem(str(p))

        # Ensure current_page is within range
        if self.current_page > total_pages:
            self.current_page = total_pages
        self.page_combo.setCurrentIndex(self.current_page - 1)
        self.page_combo.blockSignals(False)

        # Recreate widgets for the (possibly adjusted) current page
        count = self.page_button_counts.get(self.current_page)
        if count is None:
            try:
                count = int(self.button_count_combo.currentText())
            except ValueError:
                count = 6
            self.page_button_counts[self.current_page] = count

        self.button_count_combo.blockSignals(True)
        self.button_count_combo.setCurrentText(str(count))
        self.button_count_combo.blockSignals(False)
        self._create_button_widgets(count)
        self._update_preview_for_current_page()

    def _update_preview_for_current_page(self) -> None:
        if not hasattr(self, "preview_widget"):
            return

        page = self.current_page
        count = self.page_button_counts.get(page)
        if count is None:
            try:
                count = int(self.button_count_combo.currentText())
            except ValueError:
                count = 6

        labels_by_slot: dict[int, str] = {}
        widgets = self.all_button_widgets.get(page) or []
        for btn in widgets:
            text = btn.label_input.text() or f"Button {btn.slot}"
            labels_by_slot[btn.slot] = text

        self.preview_widget.update_preview(count, labels_by_slot)

    def _schedule_relayout_buttons(self) -> None:
        self._pending_relayout = True
        if hasattr(self, "_relayout_timer") and self._relayout_timer is not None:
            self._relayout_timer.start()
        else:
            self._run_pending_relayout()

    def _run_pending_relayout(self) -> None:
        if not self._pending_relayout:
            return
        self._pending_relayout = False
        self._relayout_buttons()

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "scroll_area")
            and self.scroll_area is not None
            and watched is self.scroll_area.viewport()
            and event.type() == event.Type.Resize
        ):
            self._schedule_relayout_buttons()
        return super().eventFilter(watched, event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._schedule_relayout_buttons()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_relayout_buttons()

    def closeEvent(self, event) -> None:
        if hasattr(self, "preview_dialog") and self.preview_dialog is not None:
            self.preview_dialog.close()
        super().closeEvent(event)

    def _show_fake_control_panel(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Control Panel - {self.pad_data.get('name', 'DisplayPad')}")
        dlg.resize(460, 340)
        dlg.setStyleSheet(self.styleSheet())
        layout = QVBoxLayout(dlg)

        header = QLabel(self.pad_data.get("name", "DisplayPad"))
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']};")
        layout.addWidget(header)

        subtitle = QLabel("Preview control panel")
        subtitle.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']};")
        layout.addWidget(subtitle)

        info_frame = QFrame()
        info_frame.setStyleSheet(f"QFrame {{ background: {CYBERPUNK_COLORS['bg_panel']}; border: 1px solid {CYBERPUNK_COLORS['neon_cyan']}40; border-radius: 8px; padding: 10px; }}")
        info_grid = QGridLayout(info_frame)
        info_grid.addWidget(QLabel("Mode"), 0, 0)
        active_profile = self._find_layout_profile(self.active_layout_profile)
        mode_text, pages_text = self._profile_summary_text(active_profile or self._capture_layout_snapshot(self.active_layout_profile or "Default"))
        mode_value = QLabel(mode_text)
        info_grid.addWidget(mode_value, 0, 1)
        info_grid.addWidget(QLabel("Layout"), 1, 0)

        profile_combo = QComboBox()
        for profile in self.layout_profiles:
            profile_name = str(profile.get("name", "") or "").strip()
            if profile_name:
                profile_combo.addItem(profile_name)
        if self.active_layout_profile:
            idx = profile_combo.findText(self.active_layout_profile, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                profile_combo.setCurrentIndex(idx)
        info_grid.addWidget(profile_combo, 1, 1)

        info_grid.addWidget(QLabel("Pages"), 2, 0)
        pages_value = QLabel(pages_text)
        info_grid.addWidget(pages_value, 2, 1)

        time_format = "24-hour" if self.time_format_combo.currentIndex() == 1 else "12-hour"
        if self.time_format_combo.currentIndex() == 0 and self.ampm_checkbox.isChecked():
            time_format = f"{time_format} with AM/PM"
        info_grid.addWidget(QLabel("Clock"), 3, 0)
        info_grid.addWidget(QLabel(time_format), 3, 1)

        lock_text = "Blank when host locked" if self.blank_on_lock_checkbox.isChecked() else "Stay visible when host locked"
        info_grid.addWidget(QLabel("Screen"), 4, 0)
        info_grid.addWidget(QLabel(lock_text), 4, 1)

        pin_text = f"{int(self.control_panel_policy.get('pin_length', 4) or 4)} digits • {int(self.control_panel_policy.get('max_attempts', 5) or 5)} tries"
        info_grid.addWidget(QLabel("Security"), 5, 0)
        info_grid.addWidget(QLabel(pin_text), 5, 1)
        layout.addWidget(info_frame)

        description = QLabel("This simulated control panel follows the active pad profile and lets you preview layout switching before saving it to the hardware.")
        description.setWordWrap(True)
        description.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']};")
        layout.addWidget(description)

        def _on_profile_pick(profile_name: str) -> None:
            chosen = self._find_layout_profile(profile_name)
            if chosen is None:
                return
            self.profile_combo.setCurrentText(profile_name)
            summary_mode, summary_pages = self._profile_summary_text(chosen)
            mode_value.setText(summary_mode)
            pages_value.setText(summary_pages)

        profile_combo.currentTextChanged.connect(_on_profile_pick)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    def _update_preview_clock(self) -> None:
        if hasattr(self, "preview_time_label") and self.preview_time_label is not None:
            now = datetime.now()
            if hasattr(self, "time_format_combo") and self.time_format_combo.currentIndex() == 1:
                self.preview_time_label.setText(now.strftime("%H:%M"))
            else:
                base_time = now.strftime("%I:%M").lstrip("0")
                if hasattr(self, "ampm_checkbox") and self.ampm_checkbox.isChecked():
                    base_time = f"{base_time} {now.strftime('%p')}"
                self.preview_time_label.setText(base_time)

    def _load_icon_list(self) -> None:
        """Fetch available icons from the API and cache their IDs."""
        start = time.time()
        try:
            resp = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/icons",
                timeout=3,
            )
            if resp.status_code != 200:
                print(f"[GUI] _load_icon_list HTTP {resp.status_code}", flush=True)
                return
            data = resp.json() or []
            self.available_icons = sorted({item.get("icon_id", "") for item in data if item.get("icon_id")})
            duration = (time.time() - start) * 1000.0
            print(f"[GUI] _load_icon_list loaded {len(self.available_icons)} icons in {duration:.1f} ms", flush=True)
        except Exception as e:
            print(f"[GUI] Failed to load icon list: {e}", flush=True)

    def _load_macro_list(self) -> None:
        """Load predefined macros from the local database.

        Macros are stored in the `macros` table and referenced by
        buttons.action_id. Here we load all macros of type
        'key_sequence_v2' so they can be assigned to buttons.
        """

        self.available_macros: list[dict] = []
        self._macro_by_action_id: dict[str, dict] = {}
        try:
            config = _get_config()
            with _db_connect(config.database_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT action_id, name, type, payload_json, enabled, permission_level
                    FROM macros
                    WHERE type = 'key_sequence_v2'
                    ORDER BY name COLLATE NOCASE
                    """
                )
                rows = cursor.fetchall()
        except Exception as e:
            print(f"[GUI] Failed to load macros: {e}", flush=True)
            return

        for row in rows:
            rec = {
                "action_id": row["action_id"],
                "name": row["name"],
                "type": row["type"],
                "enabled": bool(row["enabled"]),
                "permission_level": row["permission_level"],
            }
            self.available_macros.append(rec)
            self._macro_by_action_id[rec["action_id"]] = rec

    def refresh_macros(self) -> None:
        """Reload macros and update all macro dropdowns while preserving selections."""

        # Remember the currently selected macro for each button widget.
        selections: dict[int, str | None] = {}
        for widgets in self.all_button_widgets.values():
            for btn in widgets:
                if btn.action_type.currentText() == "Macro":
                    selections[id(btn)] = btn.macro_combo.currentData()

        # Reload from the database.
        self._load_macro_list()

        # Repopulate every widget's macro combo and restore previous selections when possible.
        for widgets in self.all_button_widgets.values():
            for btn in widgets:
                previous = selections.get(id(btn))
                self._populate_macro_combo(btn)
                if previous:
                    idx = btn.macro_combo.findData(previous)
                    if idx >= 0:
                        btn.macro_combo.setCurrentIndex(idx)

    def _populate_macro_combo(self, widget: ButtonConfigWidget) -> None:
        """Populate a ButtonConfigWidget's macro combo with available macros."""

        # Remember the currently selected macro so we can preserve it when
        # rebuilding the list (e.g. after reopening the configurator or when
        # the macro list is refreshed).
        previous_action_id = widget.macro_combo.currentData() if widget.macro_combo.count() > 0 else None
        pending_action_id = getattr(widget, "_pending_macro_action_id", None)

        widget.macro_combo.blockSignals(True)
        widget.macro_combo.clear()
        widget.macro_combo.addItem("(No macro)", None)
        for macro in getattr(self, "available_macros", []) or []:
            widget.macro_combo.addItem(macro["name"], macro["action_id"])

        # Restore the previous selection if it still exists in the list.
        if isinstance(previous_action_id, str) and previous_action_id:
            idx = widget.macro_combo.findData(previous_action_id)
            if idx >= 0:
                widget.macro_combo.setCurrentIndex(idx)
        elif isinstance(pending_action_id, str) and pending_action_id:
            idx = widget.macro_combo.findData(pending_action_id)
            if idx >= 0:
                widget.macro_combo.setCurrentIndex(idx)
                widget._pending_macro_action_id = None

        widget.macro_combo.blockSignals(False)

    def _populate_icon_combo(self, widget: ButtonConfigWidget) -> None:
        """Populate a ButtonConfigWidget's icon combo with available icons.

        First entry is "None". New widgets default to 'stars' if present
        (matching stars.png in the icons folder).
        """
        # If this widget already has the full, current icon list, skip work.
        expected_count = (len(self.available_icons) or 0) + 1  # +1 for "None"
        if getattr(widget, "_icons_loaded", False) and widget.icon_combo.count() == expected_count:
            return

        # Remember the currently selected icon (if any) before we rebuild the list
        previous = widget.icon_combo.currentText() if widget.icon_combo.count() > 0 else "None"
        pending_icon_id = getattr(widget, "_pending_icon_id", None)

        widget.icon_combo.blockSignals(True)
        widget.icon_combo.clear()
        widget.icon_combo.addItem("None")
        for icon_id in self.available_icons:
            widget.icon_combo.addItem(icon_id)

        # If there was a previous non-empty selection, try to preserve it
        if previous and previous not in ("None", ""):
            idx = widget.icon_combo.findText(previous)
            if idx >= 0:
                widget.icon_combo.setCurrentIndex(idx)
        elif isinstance(pending_icon_id, str) and pending_icon_id:
            idx = widget.icon_combo.findText(pending_icon_id)
            if idx >= 0:
                widget.icon_combo.setCurrentIndex(idx)
                widget._pending_icon_id = None
        else:
            # Default selection for brand new widgets: 'stars' if available
            if "stars" in self.available_icons:
                idx = widget.icon_combo.findText("stars")
                if idx >= 0 and widget.icon_combo.currentText() == "None":
                    widget.icon_combo.setCurrentIndex(idx)

        widget.icon_combo.blockSignals(False)
        # Mark this widget as having been populated with the current icon list
        widget._icons_loaded = True

    def apply_cyberpunk_theme(self):
        """Apply Cyberpunk theme to dialog."""
        self.setStyleSheet(f"""
            QDialog {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
            }}
            QLabel {{
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
            QFrame {{
                background: transparent;
            }}
            QPushButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.5 {CYBERPUNK_COLORS["bg_panel"]},
                    stop: 1 {CYBERPUNK_COLORS["gothic_primary"]}24
                );
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}88;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 10px 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.5 {CYBERPUNK_COLORS["gothic_primary"]}32,
                    stop: 1 {CYBERPUNK_COLORS["gothic_primary"]}18
                );
            }}
            QLineEdit, QComboBox, QTextEdit, QPlainTextEdit {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}55;
                border-radius: 10px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 8px 10px;
            }}
            QComboBox QAbstractItemView {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                color: {CYBERPUNK_COLORS["text_white"]};
                selection-background-color: {CYBERPUNK_COLORS["gothic_primary"]}55;
            }}
            QCheckBox, QRadioButton {{
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
        """)

    def _normalize_layout_profile(self, snapshot: dict, fallback_name: str | None = None) -> dict | None:
        if not isinstance(snapshot, dict):
            return None

        name = str(snapshot.get("name") or fallback_name or "").strip()
        if not name:
            return None

        allowed = [6, 8, 10, 12, 16, 20, 24, 28, 32]
        time_cfg = snapshot.get("time") if isinstance(snapshot.get("time"), dict) else {}
        raw_counts = snapshot.get("page_button_counts") or []
        page_counts: list[int] = []
        for value in raw_counts:
            try:
                count = int(value)
            except (TypeError, ValueError):
                continue
            page_counts.append(min(allowed, key=lambda n: abs(n - count)))

        try:
            raw_page_count = int(snapshot.get("page_count", len(page_counts) or 1) or 1)
        except (TypeError, ValueError):
            raw_page_count = len(page_counts) or 1
        page_count = max(1, min(4, raw_page_count))

        if not page_counts:
            try:
                button_count = int(snapshot.get("button_count", 6) or 6)
            except (TypeError, ValueError):
                button_count = 6
            button_count = min(allowed, key=lambda n: abs(n - button_count))
            page_counts = [button_count for _ in range(page_count)]
        elif len(page_counts) < page_count:
            page_counts.extend([page_counts[-1]] * (page_count - len(page_counts)))
        else:
            page_counts = page_counts[:page_count]

        normalized = dict(snapshot)
        normalized["name"] = name
        normalized["type"] = "task" if snapshot.get("type") == "task" or snapshot.get("pad_mode") == "task_keypad" else "macro"
        normalized["page_count"] = page_count
        normalized["page_button_counts"] = page_counts
        normalized["button_count"] = page_counts[0] if page_counts else 6
        normalized["buttons"] = list(snapshot.get("buttons") or [])
        normalized["time_use_24h"] = bool(snapshot.get("time_use_24h", time_cfg.get("use_24h", False)))
        normalized["time_show_am_pm"] = bool(snapshot.get("time_show_am_pm", time_cfg.get("show_am_pm", True)))
        normalized["blank_on_lock"] = bool(snapshot.get("blank_on_lock", True))
        return normalized

    def _get_current_page_counts(self) -> list[int]:
        total_pages = self.page_count_combo.currentIndex() + 1
        page_counts: list[int] = []
        for page in range(1, total_pages + 1):
            count = self.page_button_counts.get(page)
            if count is None:
                try:
                    count = int(self.button_count_combo.currentText())
                except ValueError:
                    count = 6
            page_counts.append(max(1, min(32, int(count))))
        return page_counts

    def _capture_layout_snapshot(self, name: str | None = None) -> dict:
        page_counts = self._get_current_page_counts()
        buttons: list[dict] = []
        for page in range(1, len(page_counts) + 1):
            widgets = self.all_button_widgets.get(page) or []
            for btn in widgets[: page_counts[page - 1]]:
                cfg = btn.get_config()
                cfg["page"] = page
                buttons.append(cfg)

        snapshot = {
            "name": name or self.active_layout_profile or "Default",
            "type": "task" if self.task_radio.isChecked() else "macro",
            "buttons": buttons,
            "button_count": page_counts[0] if page_counts else 6,
            "page_count": len(page_counts) or 1,
            "page_button_counts": page_counts,
            "time_use_24h": self.time_format_combo.currentIndex() == 1,
            "time_show_am_pm": self.ampm_checkbox.isChecked(),
            "blank_on_lock": self.blank_on_lock_checkbox.isChecked(),
        }
        return self._normalize_layout_profile(snapshot, snapshot["name"]) or snapshot

    def _find_layout_profile(self, name: str | None) -> dict | None:
        if not name:
            return None
        for profile in self.layout_profiles:
            if str(profile.get("name", "") or "").strip() == name:
                return profile
        return None

    def _refresh_profile_combo(self) -> None:
        if not hasattr(self, "profile_combo"):
            return
        selected_name = self.active_layout_profile or (self.layout_profiles[0].get("name") if self.layout_profiles else "")
        self._syncing_profile_combo = True
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for profile in self.layout_profiles:
            profile_name = str(profile.get("name", "") or "").strip()
            if profile_name:
                self.profile_combo.addItem(profile_name)
        if selected_name:
            idx = self.profile_combo.findText(str(selected_name), Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)
        self._syncing_profile_combo = False

    def _store_active_profile_snapshot(self) -> None:
        if not self.active_layout_profile:
            return
        snapshot = self._capture_layout_snapshot(self.active_layout_profile)
        existing = self._find_layout_profile(self.active_layout_profile)
        if existing is not None:
            existing.clear()
            existing.update(snapshot)
        else:
            self.layout_profiles.append(snapshot)

    def _load_editor_state_from_api_config(self, data: dict) -> None:
        mode = data.get("pad_mode", "macro_keypad")
        self.task_radio.setChecked(mode == "task_keypad")
        self.macro_radio.setChecked(mode != "task_keypad")

        time_cfg = data.get("time") or {}
        use_24h = bool(time_cfg.get("use_24h", False))
        show_am_pm = bool(time_cfg.get("show_am_pm", True))
        self.time_format_combo.setCurrentIndex(1 if use_24h else 0)
        self.ampm_checkbox.setChecked(show_am_pm)
        self.blank_on_lock_checkbox.setChecked(bool(data.get("blank_on_lock", True)))

        api_page_count = int(data.get("page_count", 1) or 1)
        api_page_counts = data.get("page_button_counts") or []
        allowed = [6, 8, 10, 12, 16, 20, 24, 28, 32]
        page_counts: list[int] = []
        for index in range(api_page_count):
            if index < len(api_page_counts):
                try:
                    count = int(api_page_counts[index])
                except (TypeError, ValueError):
                    count = 6
            else:
                count = 6
            page_counts.append(min(allowed, key=lambda n: abs(n - count)))

        if not page_counts:
            page_counts = [6]

        total_pages = min(len(page_counts), 4)
        page_counts = page_counts[:total_pages]

        self.page_button_counts.clear()
        for page_index, count in enumerate(page_counts, start=1):
            self.page_button_counts[page_index] = count

        self.page_count_combo.blockSignals(True)
        self.page_count_combo.setCurrentIndex(total_pages - 1)
        self.page_count_combo.blockSignals(False)

        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for page_index in range(1, total_pages + 1):
            self.page_combo.addItem(str(page_index))
        self.page_combo.blockSignals(False)

        offsets: list[int] = [0]
        for count in page_counts:
            offsets.append(offsets[-1] + count)

        buttons = data.get("buttons", [])
        button_map: dict[tuple[int, int], dict] = {}
        for button_cfg in buttons:
            try:
                page = int(button_cfg.get("page", 1) or 1)
                raw_slot = int(button_cfg.get("slot", 0) or 0)
            except (TypeError, ValueError):
                continue

            if page < 1 or page > total_pages or raw_slot <= 0:
                continue

            per_page_limit = page_counts[page - 1]
            local_slot = raw_slot
            if raw_slot > per_page_limit:
                local_slot = raw_slot - offsets[page - 1]
            if local_slot < 1 or local_slot > per_page_limit:
                continue

            prepared = dict(button_cfg)
            action_id = prepared.get("action_id") or ""
            if (
                action_id
                and hasattr(self, "_macro_by_action_id")
                and (
                    action_id in self._macro_by_action_id
                    or not prepared.get("application_id")
                )
            ):
                prepared["action_type"] = "Macro"
                prepared["macro_action_id"] = action_id
            elif action_id:
                prepared["action_type"] = action_id

            button_map[(page, local_slot)] = prepared

        self.all_button_widgets.clear()
        self.current_page = 1
        for page_index in range(1, total_pages + 1):
            self.current_page = page_index
            count = page_counts[page_index - 1]
            self._create_button_widgets(count)
            for widget in self.button_configs:
                cfg = button_map.get((page_index, widget.slot))
                if cfg:
                    widget.set_config(cfg)

        self.current_page = 1
        self.page_combo.setCurrentIndex(0)
        first_count = page_counts[0] if page_counts else 6
        self.button_count_combo.blockSignals(True)
        self.button_count_combo.setCurrentText(str(first_count))
        self.button_count_combo.blockSignals(False)
        self._create_button_widgets(first_count)
        self._apply_mode_to_button_widgets()
        self._update_preview_clock()
        self._update_preview_for_current_page()
        self._schedule_relayout_buttons()

    def _apply_layout_snapshot(self, snapshot: dict) -> None:
        normalized = self._normalize_layout_profile(snapshot, self.active_layout_profile or "Default")
        if normalized is None:
            return

        self.task_radio.setChecked(normalized["type"] == "task")
        self.macro_radio.setChecked(normalized["type"] != "task")
        self.time_format_combo.setCurrentIndex(1 if normalized["time_use_24h"] else 0)
        self.ampm_checkbox.setChecked(bool(normalized["time_show_am_pm"]))
        self.blank_on_lock_checkbox.setChecked(bool(normalized["blank_on_lock"]))

        page_counts = list(normalized.get("page_button_counts") or [6])
        total_pages = max(1, min(4, int(normalized.get("page_count", len(page_counts)) or len(page_counts) or 1)))
        if len(page_counts) < total_pages:
            page_counts.extend([page_counts[-1]] * (total_pages - len(page_counts)))
        else:
            page_counts = page_counts[:total_pages]

        self.page_button_counts.clear()
        for page_index, count in enumerate(page_counts, start=1):
            self.page_button_counts[page_index] = count

        self.page_count_combo.blockSignals(True)
        self.page_count_combo.setCurrentIndex(total_pages - 1)
        self.page_count_combo.blockSignals(False)

        self.page_combo.blockSignals(True)
        self.page_combo.clear()
        for page_index in range(1, total_pages + 1):
            self.page_combo.addItem(str(page_index))
        self.page_combo.blockSignals(False)

        offsets: list[int] = [0]
        for count in page_counts:
            offsets.append(offsets[-1] + count)

        buttons = normalized.get("buttons") or []
        button_map: dict[tuple[int, int], dict] = {}
        for button_cfg in buttons:
            try:
                page = int(button_cfg.get("page", 1) or 1)
                raw_slot = int(button_cfg.get("slot", 0) or 0)
            except (TypeError, ValueError):
                continue
            if page < 1 or page > total_pages:
                continue
            per_page_limit = page_counts[page - 1]
            local_slot = raw_slot
            if raw_slot > per_page_limit:
                local_slot = raw_slot - offsets[page - 1]
            if local_slot < 1 or local_slot > per_page_limit:
                continue
            prepared = dict(button_cfg)
            prepared["slot"] = local_slot
            if "icon" in prepared and "icon_id" not in prepared:
                prepared["icon_id"] = prepared.get("icon")
            action_id = prepared.get("action_id") or ""
            if (
                action_id
                and hasattr(self, "_macro_by_action_id")
                and (
                    action_id in self._macro_by_action_id
                    or not prepared.get("application_id")
                )
            ):
                prepared["action_type"] = "Macro"
                prepared["macro_action_id"] = action_id
            elif not prepared.get("action_type") and prepared.get("action_id"):
                prepared["action_type"] = prepared.get("action_id")
            button_map[(page, local_slot)] = prepared

        self.all_button_widgets.clear()
        self.current_page = 1
        for page_index in range(1, total_pages + 1):
            self.current_page = page_index
            count = page_counts[page_index - 1]
            self._create_button_widgets(count)
            for widget in self.button_configs:
                cfg = button_map.get((page_index, widget.slot))
                if cfg:
                    widget.set_config(cfg)

        self.current_page = 1
        self.page_combo.setCurrentIndex(0)
        first_count = page_counts[0] if page_counts else 6
        self.button_count_combo.blockSignals(True)
        self.button_count_combo.setCurrentText(str(first_count))
        self.button_count_combo.blockSignals(False)
        self._create_button_widgets(first_count)
        self._apply_mode_to_button_widgets()
        self._update_preview_clock()
        self._update_preview_for_current_page()
        self._schedule_relayout_buttons()

    def _on_profile_changed(self, name: str) -> None:
        profile_name = str(name or "").strip()
        if self._syncing_profile_combo or not profile_name:
            return
        if self.active_layout_profile == profile_name:
            return
        if self.active_layout_profile:
            self._store_active_profile_snapshot()
        profile = self._find_layout_profile(profile_name)
        if profile is None:
            return
        self.active_layout_profile = profile_name
        self._apply_layout_snapshot(profile)
        self._refresh_profile_combo()

    def _create_layout_profile(self) -> None:
        name, ok = QInputDialog.getText(self, "New Layout Profile", "Profile name:")
        profile_name = str(name or "").strip()
        if not ok or not profile_name:
            return
        if self._find_layout_profile(profile_name) is not None:
            QMessageBox.warning(self, "Layout Profile", "A profile with that name already exists.")
            return
        if self.active_layout_profile:
            self._store_active_profile_snapshot()
        self.active_layout_profile = profile_name
        self.layout_profiles.append(self._capture_layout_snapshot(profile_name))
        self._refresh_profile_combo()

    def _save_layout_profile(self) -> None:
        if not self.active_layout_profile:
            self.active_layout_profile = "Default"
        self._store_active_profile_snapshot()
        self._refresh_profile_combo()

    def _rename_layout_profile(self) -> None:
        if not self.active_layout_profile:
            return
        name, ok = QInputDialog.getText(self, "Rename Layout Profile", "Profile name:", text=self.active_layout_profile)
        profile_name = str(name or "").strip()
        if not ok or not profile_name or profile_name == self.active_layout_profile:
            return
        if self._find_layout_profile(profile_name) is not None:
            QMessageBox.warning(self, "Layout Profile", "A profile with that name already exists.")
            return
        profile = self._find_layout_profile(self.active_layout_profile)
        if profile is None:
            return
        profile["name"] = profile_name
        self.active_layout_profile = profile_name
        self._store_active_profile_snapshot()
        self._refresh_profile_combo()

    def _delete_layout_profile(self) -> None:
        if not self.active_layout_profile:
            return
        if len(self.layout_profiles) <= 1:
            QMessageBox.warning(self, "Layout Profile", "At least one layout profile must remain for this pad.")
            return
        reply = QMessageBox.question(
            self,
            "Delete Layout Profile",
            f"Delete the layout profile '{self.active_layout_profile}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        old_name = self.active_layout_profile
        self.layout_profiles = [profile for profile in self.layout_profiles if str(profile.get("name", "") or "").strip() != old_name]
        self.active_layout_profile = str(self.layout_profiles[0].get("name", "") or "").strip() or None
        if self.active_layout_profile:
            profile = self._find_layout_profile(self.active_layout_profile)
            if profile is not None:
                self._apply_layout_snapshot(profile)
        self._refresh_profile_combo()

    def _profile_summary_text(self, profile: dict | None) -> tuple[str, str]:
        normalized = self._normalize_layout_profile(profile or {}, self.active_layout_profile or "Default")
        if normalized is None:
            return ("Macro keypad", "1 page • 6 buttons")
        mode_text = "Task keypad" if normalized["type"] == "task" else "Macro keypad"
        page_counts = normalized.get("page_button_counts") or [6]
        counts_text = " / ".join(str(count) for count in page_counts)
        return (mode_text, f"{len(page_counts)} page(s) • {counts_text} buttons")

    def save_config(self):
        """Save the keypad configuration."""
        if not self.layout_profiles:
            self.active_layout_profile = self.active_layout_profile or "Default"
            self.layout_profiles = [self._capture_layout_snapshot(self.active_layout_profile)]
        self._store_active_profile_snapshot()

        # Determine total pages and per-page button counts before collecting
        # button data so we only persist the currently active widgets for each
        # page. Hidden extras are kept in memory for editor convenience but
        # should not be written unless that page count is active again.
        total_pages = self.page_count_combo.currentIndex() + 1
        page_counts: list[int] = []
        for p in range(1, total_pages + 1):
            count = self.page_button_counts.get(p)
            if count is None:
                try:
                    count = int(self.button_count_combo.currentText())
                except ValueError:
                    count = 6
            page_counts.append(max(1, min(32, int(count))))

        # Collect button configs across all pages
        all_buttons: list[dict] = []
        for page in range(1, total_pages + 1):
            widgets = self.all_button_widgets.get(page) or []
            active_count = page_counts[page - 1] if page - 1 < len(page_counts) else len(widgets)
            for btn in widgets[:active_count]:
                cfg = btn.get_config()
                cfg["page"] = page
                all_buttons.append(cfg)

        config = {
            "pad_uuid": self.pad_data.get("pad_uuid"),
            "type": "task" if self.task_radio.isChecked() else "macro",
            "buttons": all_buttons,
            # Backwards-compatible: keep a single button_count (page 1)
            "button_count": page_counts[0] if page_counts else 6,
            "page_count": total_pages,
            "page_button_counts": page_counts,
            "layout_profiles": self.layout_profiles,
            "active_layout_profile": self.active_layout_profile,
        }

        # Per-pad time configuration
        config["time_use_24h"] = self.time_format_combo.currentIndex() == 1
        config["time_show_am_pm"] = self.ampm_checkbox.isChecked()

        # Per-pad host lock behavior
        config["blank_on_lock"] = self.blank_on_lock_checkbox.isChecked()

        try:
            response = requests.post(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads/{self.pad_data.get('pad_uuid')}/config",
                json=config,
                timeout=5
            )
            if response.status_code == 200:
                QMessageBox.information(self, "Success", "Configuration saved successfully!")
                self.accept()
            else:
                QMessageBox.warning(self, "Error", f"Failed to save: {response.status_code}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Network error: {str(e)}")

    def load_existing_config(self):
        """Load existing configuration from API and populate widgets."""
        pad_uuid = self.pad_data.get("pad_uuid")
        if not pad_uuid:
            return

        print(f"[GUI] load_existing_config start pad_uuid={pad_uuid}", flush=True)
        start_total = time.time()
        try:
            start_http = time.time()
            resp = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads/{pad_uuid}/config",
                timeout=5,
            )
            if resp.status_code != 200:
                print(f"[GUI] load_existing_config HTTP {resp.status_code}", flush=True)
                return
            http_ms = (time.time() - start_http) * 1000.0

            data = resp.json()
            print(
                f"[GUI] load_existing_config HTTP OK in {http_ms:.1f} ms, "
                f"button_count={data.get('button_count')} buttons_len={len(data.get('buttons', []))}",
                flush=True,
            )

            self.control_panel_policy = data.get("control_panel_pin") or {}
            self.layout_profiles = []
            for raw_profile in data.get("layout_profiles") or []:
                normalized = self._normalize_layout_profile(raw_profile, str(raw_profile.get("name", "") or "").strip())
                if normalized is not None:
                    self.layout_profiles.append(normalized)

            requested_profile = str(data.get("active_layout_profile") or "").strip()
            self.active_layout_profile = requested_profile or (
                str(self.layout_profiles[0].get("name", "") or "").strip() if self.layout_profiles else "Default"
            )
            if not self.active_layout_profile:
                self.active_layout_profile = "Default"

            self._load_editor_state_from_api_config(data)

            if not self.layout_profiles:
                self.layout_profiles = [self._capture_layout_snapshot(self.active_layout_profile)]
            elif self._find_layout_profile(self.active_layout_profile) is None:
                self.layout_profiles.insert(0, self._capture_layout_snapshot(self.active_layout_profile))

            self._refresh_profile_combo()

            total_ms = (time.time() - start_total) * 1000.0
            print(f"[GUI] load_existing_config complete in {total_ms:.1f} ms", flush=True)
        except Exception as e:
            print(f"[GUI] Failed to load existing config for {pad_uuid}: {e}", flush=True)


class DeviceLogWindow(QDialog):
    def __init__(self, api_port: int, initial_pad_uuid: str | None = None, initial_pad_name: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.api_port = api_port
        self.pad_uuid: str | None = initial_pad_uuid
        self._pads: list[dict] = []
        self.setWindowTitle("Device Logs")
        self.resize(900, 600)

        layout = QVBoxLayout(self)

        header = QLabel("View ESP32 Device Logs")
        header.setWordWrap(True)
        layout.addWidget(header)

        device_row = QHBoxLayout()
        device_row.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        device_row.addWidget(self.device_combo)
        device_row.addStretch()
        layout.addLayout(device_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(split)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.sessions_list = QListWidget()
        self.sessions_list.itemSelectionChanged.connect(self.on_session_selected)
        left_layout.addWidget(QLabel("Boot Sessions:"))
        left_layout.addWidget(self.sessions_list)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Log Output:"))
        header_row.addStretch()
        self.follow_checkbox = QCheckBox("Follow live")
        self.follow_checkbox.setChecked(True)
        header_row.addWidget(self.follow_checkbox)
        right_layout.addLayout(header_row)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        right_layout.addWidget(self.log_view)
        split.addWidget(right)

        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)

        buttons = QHBoxLayout()
        self.refresh_btn = CyberpunkButton("Refresh", "cyan")
        self.refresh_btn.clicked.connect(self.refresh_sessions)
        buttons.addWidget(self.refresh_btn)
        buttons.addStretch()
        close_btn = CyberpunkButton("Close", "purple")
        close_btn.clicked.connect(self.close)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._maybe_auto_refresh)
        self._timer.start()

        self.device_combo.currentIndexChanged.connect(self.on_device_changed)
        self._load_devices(initial_pad_uuid, initial_pad_name)

    def _load_devices(self, initial_pad_uuid: str | None, initial_pad_name: str | None) -> None:
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self._pads = []
        try:
            resp = requests.get(f"http://127.0.0.1:{self.api_port}/api/v1/pads/", timeout=5)
            if resp.status_code != 200:
                self.device_combo.blockSignals(False)
                return
            data = resp.json() or {}
            pads = data.get("pads", [])
        except Exception:
            self.device_combo.blockSignals(False)
            return

        self._pads = pads
        selected_index = -1
        for idx, pad in enumerate(pads):
            pad_uuid = pad.get("pad_uuid") or ""
            name = pad.get("name") or pad_uuid
            label = f"{name} ({pad_uuid})" if pad_uuid else name
            self.device_combo.addItem(label, userData=pad_uuid)
            if initial_pad_uuid and pad_uuid == initial_pad_uuid:
                selected_index = idx

        if self.device_combo.count() > 0:
            if selected_index >= 0:
                self.device_combo.setCurrentIndex(selected_index)
            else:
                self.device_combo.setCurrentIndex(0)
            self.pad_uuid = self.device_combo.currentData()
            self.device_combo.blockSignals(False)
            self.refresh_sessions()
        else:
            self.pad_uuid = None
            self.device_combo.blockSignals(False)

    def on_device_changed(self, index: int) -> None:
        if index < 0:
            self.pad_uuid = None
            self.sessions_list.clear()
            self.log_view.clear()
            return
        pad_uuid = self.device_combo.itemData(index)
        self.pad_uuid = pad_uuid
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        self.sessions_list.clear()
        self.log_view.clear()
        if not self.pad_uuid:
            return
        try:
            resp = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads/{self.pad_uuid}/logs/sessions",
                timeout=3,
            )
            if resp.status_code != 200:
                return
            sessions = resp.json() or []
        except Exception:
            return

        for sess in sessions:
            started = sess.get("started_at", "")
            reason = sess.get("reboot_reason") or ""
            fw = sess.get("fw_version") or ""
            label = started
            if reason:
                label += f" | {reason}"
            if fw:
                label += f" | FW {fw}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, sess.get("session_uuid"))
            self.sessions_list.addItem(item)

        if self.sessions_list.count() > 0:
            self.sessions_list.setCurrentRow(0)

    def on_session_selected(self) -> None:
        items = self.sessions_list.selectedItems()
        if not items:
            self.log_view.clear()
            return
        session_uuid = items[0].data(Qt.ItemDataRole.UserRole)
        if not session_uuid:
            self.log_view.clear()
            return
        try:
            resp = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads/{self.pad_uuid}/logs",
                params={"session_uuid": session_uuid, "limit": 5000},
                timeout=5,
            )
            if resp.status_code != 200:
                self.log_view.clear()
                return
            logs = resp.json() or []
        except Exception:
            self.log_view.clear()
            return

        lines: list[str] = []
        for entry in logs:
            ts = entry.get("created_at", "")
            level = entry.get("level") or ""
            msg = entry.get("message", "")
            if level:
                lines.append(f"{ts} [{level}] {msg}")
            else:
                lines.append(f"{ts} {msg}")
        self.log_view.setPlainText("\n".join(lines))
        # Scroll to bottom
        bar = self.log_view.verticalScrollBar()
        if bar is not None:
            bar.setValue(bar.maximum())

    def _maybe_auto_refresh(self) -> None:
        if not self.follow_checkbox.isChecked():
            return
        # Re-fetch logs for the currently selected session
        self.on_session_selected()


class ApplicationLibraryWindow(QDialog):
    """Simple Application Library viewer/editor.

    This window reads from the `applications` table via the shared
    repository and allows the user to browse and search applications.
    Management actions (add/edit/delete/disable/test launch/rescan)
    are currently stubbed with informational dialogs.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Library")
        # 600px primary area + 300px side detail pane, 800px tall
        self.setMinimumSize(900, 800)
        self.resize(900, 800)
        self._apps: list = []
        self.setup_ui()
        self.refresh_list()


class CommonAppsStatsWindow(QDialog):
    """Dialog showing per-application usage statistics.

    This reads from the `applications` table and displays each program's
    usage_score so you can see which apps are most frequently running on
    this PC, sorted from most used to least used.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Application Usage Statistics")
        self.setMinimumSize(800, 600)
        self._rows: list[dict] = []
        self._setup_ui()
        self._refresh_stats()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        header = QLabel("APPLICATION USAGE STATISTICS")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 14px; font-weight: bold;"
        )
        layout.addWidget(header)

        info = QLabel(
            "This table shows programs from the Application Library and "
            "how often they have been observed running. Usage count "
            "increments periodically in the background whenever a "
            "matching process is detected. Use the checkbox below to "
            "hide entries that have never been observed running (usage = 0)."
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 11px;")
        layout.addWidget(info)

        # Filter to hide apps that have never been observed running.
        filter_row = QHBoxLayout()
        self.hide_zero_checkbox = QCheckBox("Hide apps with 0 usage")
        self.hide_zero_checkbox.setChecked(True)
        self.hide_zero_checkbox.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['neon_yellow']}; font-weight: bold;"
        )
        self.hide_zero_checkbox.stateChanged.connect(self._apply_filters)
        filter_row.addWidget(self.hide_zero_checkbox)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Usage",
            "Program",
            "Enabled",
            "Path",
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        layout.addWidget(self.table, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _refresh_stats(self) -> None:
        """Load usage statistics from the applications table."""

        try:
            cfg = _get_config()
            with _db_connect(cfg.database_path) as conn:
                cur = conn.execute(
                    """
                    SELECT
                        name,
                        executable_path,
                        enabled,
                        usage_score
                    FROM applications
                    ORDER BY usage_score DESC, name COLLATE NOCASE
                    """
                )
                rows = cur.fetchall()
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[GUI] Failed to load usage statistics: {e}", flush=True)
            rows = []

        self._rows = [
            {
                "name": row["name"] or "",
                "exe": row["executable_path"] or "",
                "enabled": bool(row["enabled"]),
                "usage": int(row["usage_score"] or 0),
            }
            for row in rows
        ]

        self._apply_filters()

        # Ensure initial focus so the user can scroll immediately.
        self.table.setFocus()

    def _apply_filters(self) -> None:
        """Apply hide-zero-usage filter and repopulate the stats table."""

        from pathlib import Path as _Path

        hide_zero = getattr(self, "hide_zero_checkbox", None)
        hide_zero_on = bool(hide_zero and hide_zero.isChecked())

        rows = [r for r in self._rows if (not hide_zero_on or r["usage"] > 0)]

        self.table.setRowCount(len(rows))

        for i, rec in enumerate(rows):
            name = rec["name"]
            exe = rec["exe"]
            program = _Path(exe).name if exe else ""
            usage = str(rec["usage"])
            enabled_text = "Yes" if rec["enabled"] else "No"

            def _item(text: str) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return item

            self.table.setItem(i, 0, _item(name))
            self.table.setItem(i, 1, _item(usage))
            self.table.setItem(i, 2, _item(program))
            self.table.setItem(i, 3, _item(enabled_text))
            self.table.setItem(i, 4, _item(exe))

        # Default sort: Usage column descending (most used at top).
        self.table.sortItems(1, Qt.SortOrder.DescendingOrder)


class ProfileBuilderDialog(QDialog):
    def __init__(self, api_port: int = 7443, parent=None):
        super().__init__(parent)
        self.api_port = api_port
        self._pads: list[dict] = []
        self.setWindowTitle("Profile Builder")
        self.setMinimumSize(720, 460)
        self.resize(760, 500)
        self._setup_ui()
        self._load_pads()

    def _setup_ui(self) -> None:
        self.setStyleSheet(f"""
            QDialog {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
            }}
            QLabel {{
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}40;
                border-radius: 16px;
            }}
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_input"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}45;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
            QListWidget::item {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}30;
                border-radius: 10px;
                padding: 12px;
                margin: 4px 0px;
            }}
            QListWidget::item:selected {{
                background: {CYBERPUNK_COLORS["gothic_primary"]}22;
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
            QPushButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.5 {CYBERPUNK_COLORS["bg_panel"]},
                    stop: 1 {CYBERPUNK_COLORS["gothic_primary"]}24
                );
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}88;
                border-radius: 12px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 10px 18px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["bg_elevated"]},
                    stop: 0.5 {CYBERPUNK_COLORS["gothic_primary"]}32,
                    stop: 1 {CYBERPUNK_COLORS["gothic_primary"]}18
                );
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QLabel("PROFILE BUILDER")
        header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_purple']}; font-size: 18px; font-weight: bold;")
        layout.addWidget(header)

        intro = QLabel(
            "Choose a connected pad to build and manage layout profiles. "
            "This opens the keypad configurator with live preview and per-pad profile switching."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 12px;")
        layout.addWidget(intro)

        card = QFrame()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 16, 16, 16)
        card_layout.setSpacing(12)

        section = QLabel("CONNECTED PADS")
        section.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 12px; font-weight: bold;")
        card_layout.addWidget(section)

        self.pad_list = QListWidget()
        self.pad_list.itemDoubleClicked.connect(lambda _item: self._open_selected_pad())
        card_layout.addWidget(self.pad_list, 1)

        self.empty_label = QLabel("")
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 11px;")
        card_layout.addWidget(self.empty_label)

        layout.addWidget(card, 1)

        buttons = QHBoxLayout()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._load_pads)
        buttons.addWidget(self.refresh_btn)

        buttons.addStretch()

        self.open_btn = QPushButton("Open Selected Pad")
        self.open_btn.clicked.connect(self._open_selected_pad)
        buttons.addWidget(self.open_btn)

        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)

    def _load_pads(self) -> None:
        self._pads = []
        self.pad_list.clear()
        try:
            response = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/pads",
                timeout=3,
            )
            if response.status_code == 200:
                data = response.json() or {}
                self._pads = list(data.get("pads", []))
        except Exception:
            self._pads = []

        for pad in self._pads:
            item = QListWidgetItem(
                f"📟 {pad.get('name', 'Unknown Pad')}\n   ID: {pad.get('pad_uuid', 'N/A')[:20]}..."
            )
            item.setData(Qt.ItemDataRole.UserRole, pad)
            item.setSizeHint(QSize(0, 62))
            self.pad_list.addItem(item)

        if self._pads:
            self.empty_label.setText("Double-click a pad or use Open Selected Pad to launch its profile editor.")
            self.pad_list.setCurrentRow(0)
        else:
            self.empty_label.setText("No pads are currently connected. When a pad appears, you can open it here to build profiles.")

    def _open_selected_pad(self) -> None:
        item = self.pad_list.currentItem()
        if item is None:
            QMessageBox.information(self, "Profile Builder", "Select a pad to open its profile editor.")
            return

        pad_data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(pad_data, dict):
            QMessageBox.warning(self, "Profile Builder", "The selected pad could not be opened.")
            return

        dialog = KeypadConfigDialog(pad_data, self.api_port, self)
        dialog.exec()
        self._load_pads()


class AddStepDialog(QDialog):
    """Dialog that captures keystrokes for a single macro step.

    Keys are recorded as a comma-separated list of tokens (e.g.
    "ALT, CTRL, F"). The user edits using on-screen Backspace and Clear
    buttons so that physical Backspace is treated as a real key event
    instead of editing the text field.
    """

    def __init__(self, parent=None, step_text: str = "", title: str = "Add Step"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._keys: list[str] = []
        self._build_ui()
        self._set_step_text(step_text)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        prompt = QLabel(
            "Press the keys for this step. Use the Backspace and Clear buttons\n"
            "below to edit the captured keystrokes."
        )
        prompt.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self.capture_edit = QLineEdit()
        self.capture_edit.setReadOnly(True)
        self.capture_edit.setPlaceholderText("Press keys now...")
        self.capture_edit.setStyleSheet(
            f"""
            QLineEdit {{
                background: {CYBERPUNK_COLORS['bg_panel']};
                border: 2px solid {CYBERPUNK_COLORS['neon_cyan']};
                border-radius: 4px;
                color: {CYBERPUNK_COLORS['text_white']};
                padding: 6px;
            }}
            """
        )
        layout.addWidget(self.capture_edit)

        btn_row = QHBoxLayout()
        self.backspace_btn = QPushButton("Backspace")
        self.clear_btn = QPushButton("Clear")
        btn_row.addWidget(self.backspace_btn)
        btn_row.addWidget(self.clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.backspace_btn.clicked.connect(self._on_backspace_clicked)
        self.clear_btn.clicked.connect(self._on_clear_clicked)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # Ensure initial focus so key presses are captured immediately.
        self.capture_edit.setFocus()

    def _update_display(self) -> None:
        self.capture_edit.setText(", ".join(self._keys))

    def _set_step_text(self, step_text: str) -> None:
        self._keys = [part.strip() for part in (step_text or "").split(",") if part.strip()]
        self._update_display()

    def _modifier_tokens(self, modifiers) -> list[str]:
        tokens: list[str] = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            tokens.append("ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            tokens.append("alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            tokens.append("shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            tokens.append("meta")
        return tokens

    def _key_to_token(self, event) -> str | None:
        key = event.key()

        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return None

        base_token: str | None = None
        if key == Qt.Key.Key_Backspace:
            base_token = "backspace"
        elif key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            base_token = "enter"
        elif key == Qt.Key.Key_Tab:
            base_token = "tab"
        elif key == Qt.Key.Key_Space:
            base_token = "space"
        elif key == Qt.Key.Key_Escape:
            base_token = "escape"
        elif key == Qt.Key.Key_Delete:
            base_token = "delete"
        elif key == Qt.Key.Key_Up:
            base_token = "up"
        elif key == Qt.Key.Key_Down:
            base_token = "down"
        elif key == Qt.Key.Key_Left:
            base_token = "left"
        elif key == Qt.Key.Key_Right:
            base_token = "right"
        elif key == Qt.Key.Key_Home:
            base_token = "home"
        elif key == Qt.Key.Key_End:
            base_token = "end"
        elif key == Qt.Key.Key_PageUp:
            base_token = "pageup"
        elif key == Qt.Key.Key_PageDown:
            base_token = "pagedown"

        text = event.text() or ""
        if base_token is None and text:
            base_token = text.upper()

        if not base_token:
            return None

        modifiers = self._modifier_tokens(event.modifiers())
        if modifiers:
            return "+".join(modifiers + [base_token])
        return base_token

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key()
        modifiers = event.modifiers()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and modifiers == Qt.KeyboardModifier.NoModifier:
            if self._keys:
                self.accept()
            return

        if key == Qt.Key.Key_Escape and modifiers == Qt.KeyboardModifier.NoModifier:
            self.reject()
            return

        token = self._key_to_token(event)
        if token:
            self._keys.append(token)
            self._update_display()

    def _on_backspace_clicked(self) -> None:
        if self._keys:
            self._keys.pop()
            self._update_display()

    def _on_clear_clicked(self) -> None:
        self._keys.clear()
        self._update_display()

    def _on_accept(self) -> None:
        if not self._keys:
            QMessageBox.warning(self, "No keys", "Press at least one key for this step.")
            return
        self.accept()

    def get_step_text(self) -> str:
        """Return the captured keys as a comma-separated string."""

        return ", ".join(self._keys)


class MacroBuilderDialog(QDialog):
    """Dialog for creating and editing reusable macros.

    Macros are stored in the `macros` table and referenced from keypad
    buttons via buttons.action_id. This editor focuses on the
    'key_sequence_v2' macro type, which is a list of records, each
    containing one or more key combos and a per-record delay.
    """

    MAX_STEPS = 100

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Macro Builder")
        self.setMinimumSize(900, 600)
        self.resize(900, 600)
        self._all_macros: list[dict] = []
        self._macros: list[dict] = []
        self._current_macro: dict | None = None
        self._suppress_selection_change = False
        self._setup_macro_ui()
        self.load_macros()

    def _setup_macro_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)

        # Left side: macro list and controls
        left = QVBoxLayout()
        left.setSpacing(8)

        label = QLabel("MACROS")
        label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 12px; font-weight: bold;")
        left.addWidget(label)

        self.macro_search_edit = QLineEdit()
        self.macro_search_edit.setPlaceholderText("Search macros...")
        self.macro_search_edit.textChanged.connect(self._on_macro_search_changed)
        left.addWidget(self.macro_search_edit)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
        """)
        self.list_widget.currentRowChanged.connect(self.on_macro_selected)
        left.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.new_btn.clicked.connect(self.on_new_macro)
        btn_row.addWidget(self.new_btn)

        self.dup_btn = QPushButton("Duplicate")
        self.dup_btn.clicked.connect(self.on_duplicate_macro)
        btn_row.addWidget(self.dup_btn)

        self.del_btn = QPushButton("Delete")
        self.del_btn.clicked.connect(self.on_delete_macro)
        btn_row.addWidget(self.del_btn)
        left.addLayout(btn_row)

        layout.addLayout(left, 1)

        # Right side: macro editor
        right = QVBoxLayout()
        right.setSpacing(8)

        name_row = QHBoxLayout()
        name_label = QLabel("Name:")
        name_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Macro name (e.g. Rush)")
        self.name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 2px solid {CYBERPUNK_COLORS["neon_pink"]};
                border-radius: 4px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
        """)
        name_row.addWidget(name_label)
        name_row.addWidget(self.name_edit, 1)
        right.addLayout(name_row)

        info = QLabel(
            "Each row is a step in the macro. "
            "Use commas to separate key combos and '+' to join keys in a combo.\n"
            "Example: ALT+CTRL+F, A, T, R, O, C  (Delay = seconds before next row)"
        )
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 10px;")
        right.addWidget(info)

        self.table = QTableWidget()
        self.table.setColumnCount(2)
        self.table.setHorizontalHeaderLabels(["Keys", "Delay (sec)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setRowCount(10)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.itemSelectionChanged.connect(self._update_step_buttons)
        self.table.cellDoubleClicked.connect(self._on_step_double_clicked)
        right.addWidget(self.table, 1)

        step_btn_row = QHBoxLayout()
        self.add_step_btn = QPushButton("Add Step")
        self.add_step_btn.clicked.connect(self.on_add_step)
        step_btn_row.addWidget(self.add_step_btn)

        self.insert_above_btn = QPushButton("Insert Above")
        self.insert_above_btn.clicked.connect(self.on_insert_step_above)
        step_btn_row.addWidget(self.insert_above_btn)

        self.insert_below_btn = QPushButton("Insert Below")
        self.insert_below_btn.clicked.connect(self.on_insert_step_below)
        step_btn_row.addWidget(self.insert_below_btn)

        self.edit_step_btn = QPushButton("Edit Step")
        self.edit_step_btn.clicked.connect(self.on_edit_step)
        step_btn_row.addWidget(self.edit_step_btn)

        self.duplicate_step_btn = QPushButton("Duplicate Step")
        self.duplicate_step_btn.clicked.connect(self.on_duplicate_step)
        step_btn_row.addWidget(self.duplicate_step_btn)

        self.remove_step_btn = QPushButton("Remove Step")
        self.remove_step_btn.clicked.connect(self.on_remove_step)
        step_btn_row.addWidget(self.remove_step_btn)

        self.move_step_up_btn = QPushButton("Move Up")
        self.move_step_up_btn.clicked.connect(self.on_move_step_up)
        step_btn_row.addWidget(self.move_step_up_btn)

        self.move_step_down_btn = QPushButton("Move Down")
        self.move_step_down_btn.clicked.connect(self.on_move_step_down)
        step_btn_row.addWidget(self.move_step_down_btn)

        self.step_test_btn = QPushButton("Run Step")
        self.step_test_btn.clicked.connect(self.on_test_step)
        step_btn_row.addWidget(self.step_test_btn)

        self.test_btn = QPushButton("Run Test")
        self.test_btn.clicked.connect(self.on_test_macro)
        step_btn_row.addWidget(self.test_btn)

        step_btn_row.addStretch()
        right.addLayout(step_btn_row)

        # Status label for last test result (non-intrusive feedback).
        self.test_status_label = QLabel("")
        self.test_status_label.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 10px;"
        )
        right.addWidget(self.test_status_label)

        preview_label = QLabel("PREVIEW")
        preview_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 12px; font-weight: bold;")
        right.addWidget(preview_label)

        self.preview_summary_label = QLabel("No steps yet.")
        self.preview_summary_label.setWordWrap(True)
        self.preview_summary_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 10px;")
        right.addWidget(self.preview_summary_label)

        self.preview_edit = QPlainTextEdit()
        self.preview_edit.setReadOnly(True)
        self.preview_edit.setMinimumHeight(120)
        self.preview_edit.setStyleSheet(f"""
            QPlainTextEdit {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
        """)
        right.addWidget(self.preview_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        button_box.accepted.connect(self.on_save_macro)
        button_box.rejected.connect(self.reject)
        right.addWidget(button_box)

        layout.addLayout(right, 2)
        self._update_step_buttons()
        self.name_edit.textChanged.connect(self._update_preview)
        self.table.itemChanged.connect(self._on_table_item_changed)
        self.table.currentCellChanged.connect(self._on_table_current_cell_changed)
        self._update_preview()

    # --- Data helpers -------------------------------------------------

    def load_macros(self) -> None:
        """Load existing macros of type 'key_sequence_v2' from the database."""

        # Ensure the macro UI has been built so list_widget exists.
        if not hasattr(self, "list_widget"):
            try:
                self._setup_macro_ui()
            except Exception:
                # If UI setup fails for any reason, bail out gracefully.
                return

        preferred_action_id = self._current_macro["action_id"] if self._current_macro else None
        self._all_macros.clear()
        try:
            config = _get_config()
            with _db_connect(config.database_path) as conn:
                cursor = conn.execute(
                    """
                    SELECT id, action_id, name, type, payload_json, enabled, permission_level
                    FROM macros
                    WHERE type = 'key_sequence_v2'
                    ORDER BY name COLLATE NOCASE
                    """
                )
                rows = cursor.fetchall()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load macros: {e}")
            return

        import json as _json

        for row in rows:
            try:
                payload = _json.loads(row["payload_json"] or "{}")
            except Exception:
                payload = {}

            rec = {
                "id": row["id"],
                "action_id": row["action_id"],
                "name": row["name"],
                "type": row["type"],
                "payload": payload,
                "enabled": bool(row["enabled"]),
                "permission_level": row["permission_level"],
            }
            self._all_macros.append(rec)

        self._apply_macro_filter(preferred_action_id)

    def _find_macro_by_action_id(self, action_id: str) -> dict | None:
        for rec in self._macros:
            if rec["action_id"] == action_id:
                return rec
        return None

    def _on_macro_search_changed(self, _text: str) -> None:
        preferred_action_id = self._current_macro["action_id"] if self._current_macro else None
        self._apply_macro_filter(preferred_action_id)

    def _apply_macro_filter(self, preferred_action_id: str | None = None) -> None:
        query = (self.macro_search_edit.text() or "").strip().lower()
        if query:
            filtered = [
                rec for rec in self._all_macros
                if query in (rec.get("name") or "").lower()
                or query in (rec.get("action_id") or "").lower()
            ]
        else:
            filtered = list(self._all_macros)

        self._macros = filtered
        self._suppress_selection_change = True
        try:
            self.list_widget.clear()
            for rec in self._macros:
                item = QListWidgetItem(rec["name"])
                item.setData(Qt.ItemDataRole.UserRole, rec["action_id"])
                self.list_widget.addItem(item)

            selected_row = -1
            if self._macros:
                if preferred_action_id:
                    for idx, rec in enumerate(self._macros):
                        if rec["action_id"] == preferred_action_id:
                            selected_row = idx
                            break
                if selected_row < 0:
                    selected_row = 0
                self.list_widget.setCurrentRow(selected_row)
            else:
                self.list_widget.clearSelection()
        finally:
            self._suppress_selection_change = False

        if self._macros:
            self.on_macro_selected(self.list_widget.currentRow())
        else:
            self._current_macro = None
            self.name_edit.clear()
            self.table.clearContents()
            self.table.setRowCount(10)
            self.table.clearSelection()
            self._update_step_buttons()
            self._update_preview()

    def _ensure_delay_spinbox(self, row: int, value: int = 0) -> QSpinBox:
        spin = self.table.cellWidget(row, 1)
        if not isinstance(spin, QSpinBox):
            spin = QSpinBox(self.table)
            spin.setRange(0, 30)
            spin.setSuffix(" s")
            spin.valueChanged.connect(self._on_delay_changed)
            self.table.setCellWidget(row, 1, spin)
        was_blocked = spin.blockSignals(True)
        spin.setValue(max(0, min(int(value), 30)))
        spin.blockSignals(was_blocked)
        return spin

    def _delay_value_at_row(self, row: int) -> int:
        if row < 0 or row >= self.table.rowCount():
            return 0
        spin = self.table.cellWidget(row, 1)
        if isinstance(spin, QSpinBox):
            return int(spin.value())
        item = self.table.item(row, 1)
        text = item.text().strip() if item and item.text() else "0"
        try:
            return max(0, min(int(text or "0"), 30))
        except ValueError:
            return 0

    def _cell_text(self, row: int, column: int) -> str:
        if column == 1:
            return str(self._delay_value_at_row(row))
        item = self.table.item(row, column)
        if item is None or not item.text():
            return ""
        return item.text().strip()

    def _row_has_step(self, row: int) -> bool:
        if row < 0 or row >= self.table.rowCount():
            return False
        return bool(self._cell_text(row, 0))

    def _set_row_values(self, row: int, keys_text: str, delay_text: str) -> None:
        self.table.setItem(row, 0, QTableWidgetItem((keys_text or "").strip()))
        try:
            delay_value = int((delay_text or "0").strip() or "0")
        except ValueError:
            delay_value = 0
        self._ensure_delay_spinbox(row, delay_value)

    def _selected_step_row(self) -> int:
        row = self.table.currentRow()
        if not self._row_has_step(row):
            return -1
        return row

    def _last_step_row(self) -> int:
        for row in range(self.table.rowCount() - 1, -1, -1):
            if self._row_has_step(row):
                return row
        return -1

    def _step_count(self) -> int:
        return sum(1 for row in range(self.table.rowCount()) if self._row_has_step(row))

    def _swap_rows(self, first_row: int, second_row: int) -> None:
        first_values = (self._cell_text(first_row, 0), self._cell_text(first_row, 1))
        second_values = (self._cell_text(second_row, 0), self._cell_text(second_row, 1))
        self._set_row_values(first_row, second_values[0], second_values[1])
        self._set_row_values(second_row, first_values[0], first_values[1])

    def _update_step_buttons(self) -> None:
        selected_row = self._selected_step_row()
        has_step = selected_row >= 0
        last_row = self._last_step_row()
        self.insert_above_btn.setEnabled(has_step)
        self.insert_below_btn.setEnabled(has_step)
        self.edit_step_btn.setEnabled(has_step)
        self.duplicate_step_btn.setEnabled(has_step)
        self.remove_step_btn.setEnabled(has_step)
        self.step_test_btn.setEnabled(has_step)
        self.move_step_up_btn.setEnabled(has_step and selected_row > 0)
        self.move_step_down_btn.setEnabled(has_step and selected_row < last_row)

    def _format_key_token(self, token: str) -> str:
        pieces = [part.strip() for part in (token or "").split("+") if part.strip()]
        formatted: list[str] = []
        for piece in pieces:
            lowered = piece.lower()
            if len(lowered) == 1 and lowered.isalpha():
                formatted.append(lowered.upper())
            elif lowered in {"ctrl", "alt", "shift", "meta", "tab", "enter", "escape", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end", "pageup", "pagedown"}:
                formatted.append(lowered.capitalize())
            else:
                formatted.append(piece)
        return "+".join(formatted)

    def _format_step_preview(self, row: int) -> str:
        keys_text = self._cell_text(row, 0)
        combos = [part.strip() for part in keys_text.split(",") if part.strip()]
        combo_text = " then ".join(self._format_key_token(combo) for combo in combos) if combos else "<empty>"
        delay_value = self._delay_value_at_row(row)
        if delay_value > 0:
            delay_text = f" | wait {delay_value}s"
        else:
            delay_text = ""
        return f"{row + 1}. {combo_text}{delay_text}"

    def _update_preview(self) -> None:
        name = (self.name_edit.text() or "").strip()
        step_rows = [row for row in range(self.table.rowCount()) if self._row_has_step(row)]
        total_delay = sum(self._delay_value_at_row(row) for row in step_rows)
        title = name or "Unsaved macro"
        if step_rows:
            self.preview_summary_label.setText(
                f"{title} · {len(step_rows)} step(s) · total configured delay {total_delay}s"
            )
            self.preview_edit.setPlainText("\n".join(self._format_step_preview(row) for row in step_rows))
        else:
            self.preview_summary_label.setText(f"{title} · No steps yet.")
            self.preview_edit.setPlainText("Add steps to see a readable macro preview.")

    def _on_table_item_changed(self, _item: QTableWidgetItem) -> None:
        self._update_step_buttons()
        self._update_preview()

    def _on_table_current_cell_changed(self, _current_row: int, _current_column: int, _previous_row: int, _previous_column: int) -> None:
        self._update_step_buttons()
        self._update_preview()

    def _on_delay_changed(self, _value: int) -> None:
        self._update_preview()

    def _capture_step_text(self, title: str, step_text: str = "") -> str | None:
        dlg = AddStepDialog(self, step_text, title)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        captured = (dlg.get_step_text() or "").strip()
        return captured or None

    def _insert_step_at_row(self, row: int, keys_text: str, delay_value: int = 0) -> None:
        self.table.insertRow(row)
        self._set_row_values(row, keys_text, str(delay_value))
        self.table.setCurrentCell(row, 0)
        self._update_step_buttons()
        self._update_preview()

    def _edit_step_row(self, row: int) -> None:
        if not self._row_has_step(row):
            return
        dlg = AddStepDialog(self, self._cell_text(row, 0), "Edit Step")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._set_row_values(row, (dlg.get_step_text() or "").strip(), self._cell_text(row, 1) or "0")
        self.table.setCurrentCell(row, 0)
        self._update_step_buttons()
        self._update_preview()

    def _on_step_double_clicked(self, row: int, _column: int) -> None:
        self._edit_step_row(row)

    # --- UI actions ----------------------------------------------------

    def on_macro_selected(self, row: int) -> None:
        if self._suppress_selection_change:
            return
        if row < 0 or row >= len(self._macros):
            self._current_macro = None
            self.name_edit.clear()
            self.table.clearContents()
            self.table.clearSelection()
            self.table.setRowCount(10)
            self._update_step_buttons()
            self._update_preview()
            return

        macro = self._macros[row]
        self._current_macro = macro
        self.name_edit.setText(macro["name"])
        self._load_macro_into_table(macro["payload"])

        # If this macro currently has no steps, immediately prompt the user
        # to enter the first step so the workflow is guided.
        payload = macro.get("payload")
        records = []
        if isinstance(payload, dict):
            records = payload.get("records") or []
        if not records:
            self.on_add_step()
        else:
            self.table.setCurrentCell(0, 0)
            self._update_step_buttons()
        self._update_preview()

    def _load_macro_into_table(self, payload: dict) -> None:
        records = payload.get("records", []) if isinstance(payload, dict) else []
        self.table.clearContents()
        self.table.setRowCount(max(10, len(records)))

        for row, rec in enumerate(records):
            if not isinstance(rec, dict):
                continue
            combos = rec.get("combos") or []
            parts: list[str] = []
            for combo in combos:
                if not combo:
                    continue
                if isinstance(combo, str):
                    keys = [combo]
                else:
                    keys = [str(k) for k in combo]
                parts.append("+".join(k.upper() for k in keys))
            keys_text = ", ".join(parts)
            delay_ms = rec.get("delay_after_ms", 0) or 0
            delay_sec = max(0, min(int(delay_ms // 1000), 30))

            self._set_row_values(row, keys_text, str(delay_sec))
        if records:
            self.table.setCurrentCell(0, 0)
        else:
            self.table.clearSelection()
        self._update_step_buttons()
        self._update_preview()

    def on_new_macro(self) -> None:
        # Ask the user for the new macro's name before preparing the editor.
        name, ok = QInputDialog.getText(
            self,
            "New Macro",
            "Enter macro name:",
        )
        name = (name or "").strip()
        if not ok or not name:
            return

        self._current_macro = None
        self.name_edit.setText(name)
        self.table.clearContents()
        self.table.setRowCount(10)

        # Clear any selection in the list without triggering a reload of
        # the previous macro into the editor.
        self._suppress_selection_change = True
        try:
            self.list_widget.clearSelection()
        finally:
            self._suppress_selection_change = False
        self.table.clearSelection()
        self._update_step_buttons()

        # Put keyboard focus into the name field so the user can immediately
        # start typing or proceed to add steps.
        self.name_edit.setFocus()

        # Immediately prompt for the first step so the workflow is guided.
        self.on_add_step()

    def on_duplicate_macro(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        action_id = item.data(Qt.ItemDataRole.UserRole)
        macro = self._find_macro_by_action_id(action_id)
        if not macro:
            return
        self._current_macro = None
        self.name_edit.setText(macro["name"] + " (Copy)")
        self._load_macro_into_table(macro["payload"])
        self.list_widget.clearSelection()
        self._update_step_buttons()
        self._update_preview()

    def on_delete_macro(self) -> None:
        item = self.list_widget.currentItem()
        if not item:
            return
        action_id = item.data(Qt.ItemDataRole.UserRole)
        resp = QMessageBox.question(
            self,
            "Delete Macro",
            f"Delete macro '{item.text()}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            config = _get_config()
            with _db_connect(config.database_path) as conn:
                conn.execute("DELETE FROM macros WHERE action_id = ?", (action_id,))
                conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete macro: {e}")
            return

        self.load_macros()
        try:
            MACRO_EVENT_BUS.macros_changed.emit()
        except Exception:
            pass


    def _build_current_payload(self) -> dict | None:
        """Build a key_sequence_v2 payload from the current table.

        Shared between save and test so the behavior matches.
        """

        records: list[dict] = []
        rows = min(self.table.rowCount(), self.MAX_STEPS)
        for row in range(rows):
            item_keys = self.table.item(row, 0)
            keys_text = item_keys.text().strip() if item_keys and item_keys.text() else ""
            delay_sec = self._delay_value_at_row(row)

            if not keys_text:
                break

            combos: list[list[str]] = []
            for combo_part in keys_text.split(','):
                combo_part = combo_part.strip()
                if not combo_part:
                    continue
                keys = [k.strip().lower() for k in combo_part.split('+') if k.strip()]
                if keys:
                    combos.append(keys)

            if not combos:
                continue

            records.append({
                "combos": combos,
                "delay_after_ms": delay_sec * 1000,
            })

        if not records:
            return None

        return {"records": records}


    def _build_row_payload(self, row: int) -> dict | None:
        """Build a key_sequence_v2 payload containing only the given row.

        Used for per-step testing so behavior matches full macro parsing.
        """

        if row < 0 or row >= self.table.rowCount():
            return None

        item_keys = self.table.item(row, 0)
        keys_text = item_keys.text().strip() if item_keys and item_keys.text() else ""
        delay_sec = self._delay_value_at_row(row)

        if not keys_text:
            return None

        combos: list[list[str]] = []
        for combo_part in keys_text.split(','):
            combo_part = combo_part.strip()
            if not combo_part:
                continue
            keys = [k.strip().lower() for k in combo_part.split('+') if k.strip()]
            if keys:
                combos.append(keys)

        if not combos:
            return None

        record = {
            "combos": combos,
            "delay_after_ms": delay_sec * 1000,
        }

        return {"records": [record]}


    def on_test_macro(self) -> None:
        """Execute the current macro against the active Windows window.

        This uses the same execute_macro path as pad button presses, but
        avoids logging the actual key contents; only a summary is printed.
        """

        name = (self.name_edit.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Macro name is required before testing.")
            return

        payload = self._build_current_payload()
        if not payload:
            QMessageBox.warning(self, "Validation", "Macro has no steps to test.")
            return

        try:
            from displaypad_server.windows.sendinput import execute_macro

            # For privacy/security, do not log the macro contents here. The
            # execute_macro implementation already redacts key data.
            ok = execute_macro("key_sequence_v2", payload)
        except Exception as e:
            QMessageBox.critical(self, "Test Failed", f"Error while executing macro: {e}")
            return

        if ok:
            msg = "Macro test executed. Check the active window for output."
            self.test_status_label.setText(msg)
            self.test_status_label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 10px;"
            )
            QMessageBox.information(self, "Test", msg)
        else:
            msg = "Macro did not execute successfully."
            self.test_status_label.setText(msg)
            self.test_status_label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 10px;"
            )
            QMessageBox.warning(self, "Test", msg)


    def on_test_step(self) -> None:
        """Execute only the currently selected step against the active window."""

        row = self._selected_step_row()
        if row < 0:
            QMessageBox.warning(self, "Test Step", "Select a step row to test.")
            return

        payload = self._build_row_payload(row)
        if not payload:
            QMessageBox.warning(self, "Test Step", "Selected row has no keys to test.")
            return

        try:
            from displaypad_server.windows.sendinput import execute_macro

            ok = execute_macro("key_sequence_v2", payload)
        except Exception as e:
            msg = f"Error while executing step: {e}"
            self.test_status_label.setText(msg)
            self.test_status_label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 10px;"
            )
            QMessageBox.critical(self, "Test Step Failed", msg)
            return

        if ok:
            msg = "Step test executed. Check the active window for output."
            self.test_status_label.setText(msg)
            self.test_status_label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 10px;"
            )
            QMessageBox.information(self, "Test Step", msg)
        else:
            msg = "Step did not execute successfully."
            self.test_status_label.setText(msg)
            self.test_status_label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 10px;"
            )
            QMessageBox.warning(self, "Test Step", msg)

    def on_add_step(self) -> None:
        # Require that a macro is being edited/created before adding steps.
        name = (self.name_edit.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Macro required", "Create or select a macro before adding steps.")
            return

        # Find the first completely empty row to reuse; otherwise append.
        empty_row = None
        for r in range(self.table.rowCount()):
            item_keys = self.table.item(r, 0)
            if not item_keys or not (item_keys.text() or "").strip():
                empty_row = r
                break

        if empty_row is None:
            rows = self.table.rowCount()
            if rows >= self.MAX_STEPS:
                QMessageBox.warning(self, "Limit reached", f"Maximum of {self.MAX_STEPS} steps per macro.")
                return
            empty_row = rows
            self.table.insertRow(empty_row)

        # Use the dedicated AddStepDialog to capture keystrokes for this step.
        keys_text = self._capture_step_text("Add Step")
        if not keys_text:
            return

        self._set_row_values(empty_row, keys_text, self._cell_text(empty_row, 1) or "0")
        self.table.setCurrentCell(empty_row, 0)
        self._update_step_buttons()
        self._update_preview()

    def on_insert_step_above(self) -> None:
        row = self._selected_step_row()
        if row < 0:
            QMessageBox.information(self, "Insert Step", "Select a step row to insert above.")
            return
        if self._step_count() >= self.MAX_STEPS:
            QMessageBox.warning(self, "Limit reached", f"Maximum of {self.MAX_STEPS} steps per macro.")
            return
        keys_text = self._capture_step_text("Insert Step Above")
        if not keys_text:
            return
        self._insert_step_at_row(row, keys_text, 0)

    def on_insert_step_below(self) -> None:
        row = self._selected_step_row()
        if row < 0:
            QMessageBox.information(self, "Insert Step", "Select a step row to insert below.")
            return
        if self._step_count() >= self.MAX_STEPS:
            QMessageBox.warning(self, "Limit reached", f"Maximum of {self.MAX_STEPS} steps per macro.")
            return
        keys_text = self._capture_step_text("Insert Step Below")
        if not keys_text:
            return
        self._insert_step_at_row(row + 1, keys_text, 0)

    def on_edit_step(self) -> None:
        row = self._selected_step_row()
        if row < 0:
            QMessageBox.information(self, "Edit Step", "Select a step row to edit.")
            return
        self._edit_step_row(row)

    def on_duplicate_step(self) -> None:
        row = self._selected_step_row()
        if row < 0:
            QMessageBox.information(self, "Duplicate Step", "Select a step row to duplicate.")
            return
        if self._step_count() >= self.MAX_STEPS:
            QMessageBox.warning(self, "Limit reached", f"Maximum of {self.MAX_STEPS} steps per macro.")
            return
        insert_row = row + 1
        self.table.insertRow(insert_row)
        self._set_row_values(insert_row, self._cell_text(row, 0), self._cell_text(row, 1) or "0")
        self.table.setCurrentCell(insert_row, 0)
        self._update_step_buttons()
        self._update_preview()

    def on_move_step_up(self) -> None:
        row = self._selected_step_row()
        if row <= 0:
            return
        self._swap_rows(row, row - 1)
        self.table.setCurrentCell(row - 1, 0)
        self._update_step_buttons()
        self._update_preview()

    def on_move_step_down(self) -> None:
        row = self._selected_step_row()
        last_row = self._last_step_row()
        if row < 0 or row >= last_row:
            return
        self._swap_rows(row, row + 1)
        self.table.setCurrentCell(row + 1, 0)
        self._update_step_buttons()
        self._update_preview()

    def on_remove_step(self) -> None:
        row = self._selected_step_row()
        if row < 0:
            return
        self.table.removeRow(row)
        if self.table.rowCount() == 0:
            self.table.setRowCount(1)
        next_row = min(row, self.table.rowCount() - 1)
        if next_row >= 0 and self._row_has_step(next_row):
            self.table.setCurrentCell(next_row, 0)
        else:
            self.table.clearSelection()
        self._update_step_buttons()
        self._update_preview()

    def on_save_macro(self) -> None:
        name = (self.name_edit.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Macro name is required.")
            return

        records: list[dict] = []
        rows = min(self.table.rowCount(), self.MAX_STEPS)
        for row in range(rows):
            item_keys = self.table.item(row, 0)
            keys_text = item_keys.text().strip() if item_keys and item_keys.text() else ""
            delay_sec = self._delay_value_at_row(row)

            if not keys_text:
                # First completely blank row marks the end of the macro.
                break

            combos: list[list[str]] = []
            # Split by commas into combos, then by '+' into keys.
            for combo_part in keys_text.split(','):
                combo_part = combo_part.strip()
                if not combo_part:
                    continue
                keys = [k.strip().lower() for k in combo_part.split('+') if k.strip()]
                if keys:
                    combos.append(keys)

            if not combos:
                continue

            try:
                delay_sec = int(delay_text or "0")
            except ValueError:
                delay_sec = 0
            delay_sec = max(0, min(delay_sec, 30))

            records.append({
                "combos": combos,
                "delay_after_ms": delay_sec * 1000,
            })

        if not records:
            QMessageBox.warning(self, "Validation", "Macro has no steps.")
            return

        import json as _json

        payload = {"records": records}
        payload_json = _json.dumps(payload)

        try:
            config = _get_config()
            with _db_connect(config.database_path) as conn:
                if self._current_macro is not None:
                    # Update existing macro
                    action_id = self._current_macro["action_id"]
                    conn.execute(
                        """
                        UPDATE macros
                        SET name = ?, type = 'key_sequence_v2', payload_json = ?, enabled = 1
                        WHERE action_id = ?
                        """,
                        (name, payload_json, action_id),
                    )
                else:
                    # Create new macro with generated action_id
                    from datetime import datetime, timezone as _tz

                    ts = datetime.now(_tz.utc).strftime("%Y%m%d%H%M%S%f")
                    action_id = f"macro_{ts}"
                    conn.execute(
                        """
                        INSERT INTO macros (action_id, name, type, payload_json, enabled, permission_level)
                        VALUES (?, ?, 'key_sequence_v2', ?, 1, 'normal')
                        """,
                        (action_id, name, payload_json),
                    )
                conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save macro: {e}")
            return

        QMessageBox.information(self, "Saved", "Macro saved successfully.")
        self.load_macros()
        try:
            MACRO_EVENT_BUS.macros_changed.emit()
        except Exception:
            pass


    def setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)

        # Search bar and filters
        search_row = QHBoxLayout()
        search_label = QLabel("Search:")
        search_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search applications...")
        self.search_edit.textChanged.connect(self.refresh_list)
        self.enabled_only_check = QCheckBox("Show only enabled")
        self.enabled_only_check.setChecked(False)
        self.enabled_only_check.stateChanged.connect(self.refresh_list)
        # When checked, the list shows only applications that have been
        # observed running (usage_score > 0), sorted by most-used first.
        self.common_only_check = QCheckBox("Common apps only")
        self.common_only_check.setChecked(False)
        self.common_only_check.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['neon_yellow']}; font-weight: bold;"
        )
        self.common_only_check.stateChanged.connect(self.refresh_list)
        search_row.addWidget(search_label)
        search_row.addWidget(self.search_edit)
        search_row.addWidget(self.enabled_only_check)
        search_row.addWidget(self.common_only_check)
        layout.addLayout(search_row)

        # Main content row: table on the left, details pane on the right
        content_row = QHBoxLayout()
        layout.addLayout(content_row)

        # Applications table with sortable columns (left side)
        self.table = QTableWidget()
        self.table.setColumnCount(8)
        self.table.setHorizontalHeaderLabels([
            "Name",
            "Program",
            "Vendor",
            "Source",
            "Type",
            "Enabled",
            "Has Icon",
            "Path",
        ])
        self.table.setSortingEnabled(True)
        self.table.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumWidth(600)

        # Column widths
        self.table.setColumnWidth(0, 185)  # Name
        self.table.setColumnWidth(1, 150)  # Program
        self.table.setColumnWidth(2, 100)  # Vendor
        self.table.setColumnWidth(3, 100)  # Source
        self.table.setColumnWidth(4, 65)   # Type
        self.table.setColumnWidth(5, 55)   # Enabled
        self.table.setColumnWidth(6, 55)   # Has Icon
        self.table.setColumnWidth(7, 200)  # Path

        content_row.addWidget(self.table)

        # Details pane (right side)
        detail_container = QWidget()
        detail_container.setFixedWidth(300)
        detail_layout = QVBoxLayout(detail_container)
        detail_layout.setSpacing(6)

        detail_title = QLabel("Application Details")
        detail_title.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['text_white']}; font-weight: bold;"
        )
        detail_layout.addWidget(detail_title)

        from PyQt6.QtWidgets import QGridLayout as _QGridLayout  # local import to avoid top-level changes

        grid = _QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        self._detail_labels: dict[str, QLabel] = {}

        def _add_detail_row(row_index: int, label_text: str) -> int:
            label = QLabel(f"{label_text}:")
            label.setStyleSheet(
                f"color: {CYBERPUNK_COLORS['text_white']}; font-weight: bold;"
            )
            value = QLabel("")
            value.setWordWrap(True)
            value.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value, row_index, 1)
            self._detail_labels[label_text] = value
            return row_index + 1

        row = 0
        row = _add_detail_row(row, "Name")
        row = _add_detail_row(row, "Program")
        row = _add_detail_row(row, "Executable")
        row = _add_detail_row(row, "Working Dir")
        row = _add_detail_row(row, "Arguments")
        row = _add_detail_row(row, "Publisher")
        row = _add_detail_row(row, "Version")
        row = _add_detail_row(row, "Install Location")
        row = _add_detail_row(row, "Source")
        row = _add_detail_row(row, "Type")
        row = _add_detail_row(row, "Enabled")
        row = _add_detail_row(row, "Category")
        row = _add_detail_row(row, "Notes")
        row = _add_detail_row(row, "Shortcut")
        row = _add_detail_row(row, "Has Icon")
        row = _add_detail_row(row, "Last Scanned")
        row = _add_detail_row(row, "Created")
        row = _add_detail_row(row, "Updated")

        detail_layout.addLayout(grid)
        detail_layout.addStretch(1)
        content_row.addWidget(detail_container)

        # Update details when the selection changes
        self.table.currentCellChanged.connect(self._on_table_current_cell_changed)

        # Action buttons
        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("Add Manually")
        self.btn_edit = QPushButton("Edit")
        self.btn_delete = QPushButton("Delete")
        self.btn_disable = QPushButton("Disable")
        self.btn_test = QPushButton("Test Launch")
        self.btn_rescan = QPushButton("Rescan")
        self.btn_clear = QPushButton("Clear Library")
        self.btn_close = QPushButton("Close")

        for btn in [self.btn_add, self.btn_edit, self.btn_delete, self.btn_disable, self.btn_test, self.btn_rescan]:
            btn.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")

        # Clear button in red to indicate a destructive action
        self.btn_clear.setStyleSheet(
            f"color: {CYBERPUNK_COLORS['text_white']}; "
            f"background-color: {CYBERPUNK_COLORS['neon_red']}40; "
            f"border: 1px solid {CYBERPUNK_COLORS['neon_red']}; "
            "border-radius: 4px;"
        )

        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_edit)
        btn_row.addWidget(self.btn_delete)
        btn_row.addWidget(self.btn_disable)
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(self.btn_rescan)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch()
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

        # Wire up handlers
        self.btn_add.clicked.connect(self.on_add)
        self.btn_edit.clicked.connect(self.on_edit)
        self.btn_delete.clicked.connect(self.on_delete)
        self.btn_disable.clicked.connect(self.on_disable)
        self.btn_test.clicked.connect(self.on_test_launch)
        self.btn_rescan.clicked.connect(self.on_rescan)
        self.btn_clear.clicked.connect(self.on_clear_library)
        self.btn_close.clicked.connect(self.accept)

    def refresh_list(self) -> None:
        """Reload applications from the repository and refresh the list widget."""

        try:
            from displaypad_server import applications as app_repo

            search = self.search_edit.text().strip() if hasattr(self, "search_edit") else ""
            enabled_only = False
            if hasattr(self, "enabled_only_check"):
                enabled_only = self.enabled_only_check.isChecked()
            apps = app_repo.list_applications(enabled_only=enabled_only, search=search or None)

            # Look up usage_score values directly from the DB so we can both
            # filter (for "Common apps only") and visually highlight
            # frequently-used applications in the table.
            usage_map: dict[int, int] = {}
            if apps:
                try:
                    cfg = _get_config()
                    with _db_connect(cfg.database_path) as conn:
                        cur = conn.execute("SELECT id, usage_score FROM applications")
                        usage_map = {row["id"]: int(row["usage_score"] or 0) for row in cur.fetchall()}
                except Exception as e:
                    print(f"[GUI] Failed to load usage scores for applications: {e}", flush=True)
                    usage_map = {}

            # Optionally filter down to "common" apps (those with a
            # non-zero usage_score) and sort by usage_score descending so
            # that frequently-used apps bubble to the top.
            common_only = hasattr(self, "common_only_check") and self.common_only_check.isChecked()
            if common_only and apps and usage_map:
                try:
                    # Filter to apps with usage_score > 0
                    apps = [a for a in apps if usage_map.get(a.id, 0) > 0]

                    # Sort by most used, then by name for stability
                    apps.sort(
                        key=lambda a: (
                            -usage_map.get(a.id, 0),
                            (a.name or "").lower(),
                        )
                    )
                except Exception as e:
                    print(f"[GUI] Failed to apply common-apps filter: {e}", flush=True)
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[GUI] Failed to load applications into library window: {e}", flush=True)
            apps = []

        self._apps = list(apps)
        self.table.setRowCount(len(self._apps))

        from pathlib import Path as _Path

        # Import lazily to keep startup fast and avoid tight coupling
        try:
            from displaypad_server import application_icons as app_icons_repo
        except Exception:
            app_icons_repo = None  # type: ignore[assignment]

        for row, app in enumerate(self._apps):
            program = _Path(app.executable_path).name if app.executable_path else ""
            path = app.executable_path or ""
            vendor = app.publisher or ""
            source = app.detection_source or ""
            app_type = "Manual" if app.is_manual else "Scanned"
            enabled_text = "Yes" if app.enabled else "No"
            name = app.name or program or "(unnamed)"

            # Determine whether this application has an imported PNG icon
            has_icon_text = ""
            if app_icons_repo is not None:
                try:
                    icon_record = app_icons_repo.get_primary_icon_for_application(app.id)
                    has_icon_text = "Yes" if icon_record is not None else "No"
                except Exception:
                    has_icon_text = "No"

            def _make_item(text: str) -> QTableWidgetItem:
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                return item

            name_item = _make_item(name)
            name_item.setData(Qt.ItemDataRole.UserRole, app.id)
            # Visually emphasize "common" apps (those we have seen running
            # at least once) using the usage_score from the database.
            usage_val = 0
            try:
                # usage_map is populated above; guard in case of earlier failure.
                usage_val = usage_map.get(app.id, 0)  # type: ignore[name-defined]
            except Exception:
                usage_val = 0
            if usage_val > 0:
                # Highlight common apps with a neon yellow name and bold font,
                # and expose the usage count via tooltip.
                from PyQt6.QtGui import QColor as _QColor

                name_item.setForeground(_QColor(CYBERPUNK_COLORS["neon_yellow"]))
                font = name_item.font()
                font.setBold(True)
                name_item.setFont(font)
                name_item.setToolTip(f"Usage score: {usage_val}")
            else:
                name_item.setToolTip("Usage score: 0")
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, _make_item(program))
            self.table.setItem(row, 2, _make_item(vendor))
            self.table.setItem(row, 3, _make_item(source))
            self.table.setItem(row, 4, _make_item(app_type))
            self.table.setItem(row, 5, _make_item(enabled_text))
            self.table.setItem(row, 6, _make_item(has_icon_text))
            self.table.setItem(row, 7, _make_item(path))

        # Select the first row by default and populate the details pane
        if self._apps:
            self.table.selectRow(0)
            self._update_details_for_row(0)
        else:
            self._clear_details()

    def _selected_app_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _clear_details(self) -> None:
        if not hasattr(self, "_detail_labels"):
            return
        for value_label in self._detail_labels.values():
            value_label.setText("")

    def _update_details_for_row(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._apps):
            self._clear_details()
            return

        app = self._apps[row_index]

        try:
            from pathlib import Path as _Path
        except Exception:  # pragma: no cover - extremely unlikely
            _Path = None  # type: ignore[assignment]

        program = ""
        if _Path is not None and app.executable_path:
            try:
                program = _Path(app.executable_path).name
            except Exception:
                program = app.executable_path

        app_type = "Manual" if app.is_manual else "Scanned"
        enabled_text = "Yes" if app.enabled else "No"

        # Reuse the value already shown in the table for Has Icon, if present
        # Column 6 now holds the Has Icon text after the column reorder.
        has_icon_text = ""
        table_item = self.table.item(row_index, 6)
        if table_item is not None:
            has_icon_text = table_item.text()

        values: dict[str, str] = {
            "Name": app.name or "",
            "Program": program,
            "Executable": app.executable_path or "",
            "Working Dir": app.working_directory or "",
            "Arguments": app.arguments or "",
            "Publisher": app.publisher or "",
            "Version": app.version or "",
            "Install Location": app.install_location or "",
            "Source": app.detection_source or "",
            "Type": app_type,
            "Enabled": enabled_text,
            "Category": app.category or "",
            "Notes": app.notes or "",
            "Shortcut": app.shortcut_path or "",
            "Has Icon": has_icon_text,
            "Last Scanned": app.last_scanned_at or "",
            "Created": app.created_at or "",
            "Updated": app.updated_at or "",
        }

        for key, label in self._detail_labels.items():
            label.setText(values.get(key, ""))

    def _on_table_current_cell_changed(
        self,
        current_row: int,
        current_column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        # Ignore the column indices; we only care about which row is active
        if current_row < 0:
            self._clear_details()
            return
        self._update_details_for_row(current_row)

    def on_add(self) -> None:
        from displaypad_server import applications as app_repo

        dlg = ApplicationEditDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_values()
        try:
            app_repo.create_manual_application(
                name=data["name"],
                executable_path=data["executable_path"],
                working_directory=data["working_directory"],
                arguments=data["arguments"],
                icon_path=data["icon_path"],
                category=data["category"],
                notes=data["notes"],
                enabled=data["enabled"],
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Add Application", f"Failed to save application: {e}")
            return

        self.refresh_list()

    def on_edit(self) -> None:
        if self._selected_app_id() is None:
            QMessageBox.information(self, "Edit Application", "Select an application to edit.")
            return
        from displaypad_server import applications as app_repo

        app_id = self._selected_app_id()
        if app_id is None:
            return

        record = app_repo.get_application(app_id)
        if record is None:
            QMessageBox.warning(self, "Edit Application", "The selected application no longer exists.")
            self.refresh_list()
            return

        dlg = ApplicationEditDialog(self, record)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_values()
        try:
            app_repo.update_application(
                app_id,
                name=data["name"],
                executable_path=data["executable_path"],
                working_directory=data["working_directory"],
                arguments=data["arguments"],
                icon_path=data["icon_path"],
                category=data["category"],
                notes=data["notes"],
                enabled=data["enabled"],
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Edit Application", f"Failed to update application: {e}")
            return

        self.refresh_list()

    def on_delete(self) -> None:
        if self._selected_app_id() is None:
            QMessageBox.information(self, "Delete Application", "Select an application to delete.")
            return
        from displaypad_server import applications as app_repo

        app_id = self._selected_app_id()
        if app_id is None:
            return

        resp = QMessageBox.question(
            self,
            "Delete Application",
            "Are you sure you want to permanently delete this application from the library?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            app_repo.delete_application(app_id)
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Delete Application", f"Failed to delete application: {e}")
            return

        self.refresh_list()

    def on_disable(self) -> None:
        if self._selected_app_id() is None:
            QMessageBox.information(self, "Disable Application", "Select an application to disable.")
            return
        from displaypad_server import applications as app_repo

        app_id = self._selected_app_id()
        if app_id is None:
            return

        # Toggle enabled state based on current record
        record = app_repo.get_application(app_id)
        if record is None:
            QMessageBox.warning(self, "Disable Application", "The selected application no longer exists.")
            self.refresh_list()
            return

        try:
            app_repo.set_enabled(app_id, not record.enabled)
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Disable Application", f"Failed to update enabled state: {e}")
            return

        self.refresh_list()

    def on_test_launch(self) -> None:
        app_id = self._selected_app_id()
        if app_id is None:
            QMessageBox.information(self, "Test Launch", "Select an application to test launch.")
            return
        from displaypad_server import applications as app_repo
        from displaypad_server.application_launcher import LaunchSpec, launch_application

        record = app_repo.get_application(app_id)
        if record is None:
            QMessageBox.warning(self, "Test Launch", "The selected application no longer exists.")
            self.refresh_list()
            return

        spec = LaunchSpec(
            executable_path=record.executable_path,
            working_directory=record.working_directory,
            arguments=record.arguments,
            run_mode="normal",
        )

        ok = launch_application(spec)
        if not ok:
            QMessageBox.warning(self, "Test Launch", "Failed to launch the selected application.")
        else:
            QMessageBox.information(self, "Test Launch", "Application launch requested successfully.")

    def on_rescan(self) -> None:
        try:
            from displaypad_server import application_scanner

            stats = application_scanner.scan_installed_applications()
            QMessageBox.information(
                self,
                "Rescan",
                "Scan complete.\n\n"
                f"Candidates: {stats.get('total_candidates', 0)}\n"
                f"Added: {stats.get('added', 0)}\n"
                f"Updated: {stats.get('updated', 0)}\n"
                f"Skipped: {stats.get('skipped', 0)}",
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Rescan", f"Scanning failed: {e}")

        self.refresh_list()

    def on_clear_library(self) -> None:
        resp = QMessageBox.question(
            self,
            "Clear Application Library",
            "This will remove all applications from the library.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        try:
            from displaypad_server import applications as app_repo

            app_repo.clear_applications()
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Clear Application Library", f"Failed to clear library: {e}")
            return

        self.refresh_list()


class ApplicationEditDialog(QDialog):
    """Dialog for adding or editing an application entry manually."""

    def __init__(self, parent=None, record=None):
        super().__init__(parent)
        self.setWindowTitle("Application Details")
        self.setMinimumWidth(500)
        self._record = record
        self._build_ui()
        if record is not None:
            self._load_record(record)

    def _build_ui(self):
        layout = QVBoxLayout(self)

        form = QGridLayout()
        row = 0

        form.addWidget(QLabel("Name"), row, 0)
        self.name_edit = QLineEdit()
        form.addWidget(self.name_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Executable Path"), row, 0)
        self.exe_edit = QLineEdit()
        browse_exe = QPushButton("Browse...")
        browse_exe.clicked.connect(self._browse_exe)
        exe_row = QHBoxLayout()
        exe_row.addWidget(self.exe_edit)
        exe_row.addWidget(browse_exe)
        exe_container = QWidget()
        exe_container.setLayout(exe_row)
        form.addWidget(exe_container, row, 1)
        row += 1

        form.addWidget(QLabel("Working Directory"), row, 0)
        self.working_edit = QLineEdit()
        form.addWidget(self.working_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Arguments"), row, 0)
        self.args_edit = QLineEdit()
        form.addWidget(self.args_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Icon Path"), row, 0)
        self.icon_edit = QLineEdit()
        browse_icon = QPushButton("Browse...")
        browse_icon.clicked.connect(self._browse_icon)
        icon_row = QHBoxLayout()
        icon_row.addWidget(self.icon_edit)
        icon_row.addWidget(browse_icon)
        icon_container = QWidget()
        icon_container.setLayout(icon_row)
        form.addWidget(icon_container, row, 1)
        row += 1

        form.addWidget(QLabel("Category"), row, 0)
        self.category_edit = QLineEdit()
        form.addWidget(self.category_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Notes"), row, 0)
        self.notes_edit = QTextEdit()
        form.addWidget(self.notes_edit, row, 1)
        row += 1

        form.addWidget(QLabel("Enabled"), row, 0)
        self.enabled_check = QCheckBox()
        self.enabled_check.setChecked(True)
        form.addWidget(self.enabled_check, row, 1)
        row += 1

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse_exe(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Executable", "", "Applications (*.exe);;All Files (*)")
        if path:
            self.exe_edit.setText(path)
            # Default working directory to the exe's folder if empty
            if not self.working_edit.text().strip():
                self.working_edit.setText(str(Path(path).parent))

    def _browse_icon(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Icon", "", "Images (*.ico *.png *.jpg *.jpeg);;All Files (*)")
        if path:
            self.icon_edit.setText(path)

    def _load_record(self, record):
        self.name_edit.setText(record.name)
        self.exe_edit.setText(record.executable_path)
        if record.working_directory:
            self.working_edit.setText(record.working_directory)
        if record.arguments:
            self.args_edit.setText(record.arguments)
        if record.icon_path:
            self.icon_edit.setText(record.icon_path)
        if record.category:
            self.category_edit.setText(record.category)
        if record.notes:
            self.notes_edit.setPlainText(record.notes)
        self.enabled_check.setChecked(record.enabled)

    def get_values(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "executable_path": self.exe_edit.text().strip(),
            "working_directory": self.working_edit.text().strip() or None,
            "arguments": self.args_edit.text().strip() or None,
            "icon_path": self.icon_edit.text().strip() or None,
            "category": self.category_edit.text().strip() or None,
            "notes": self.notes_edit.toPlainText().strip() or None,
            "enabled": self.enabled_check.isChecked(),
        }


class DisplayPadMainWindow(QMainWindow):
    """Main window for DisplayPad Server GUI."""

    def __init__(self, api_port: int = 7443):
        super().__init__()
        self.api_port = api_port
        self.setWindowTitle("DisplayPad Server")
        self.setMinimumSize(1200, 800)
        self.current_pad: dict | None = None
        self.setup_ui()
        self.apply_cyberpunk_theme()

        # Periodically sample running processes to build a "common apps"
        # usage profile for the Application Library. This does not affect
        # normal operation if process inspection fails.
        self._common_apps_timer = QTimer(self)
        # Sample once per hour
        self._common_apps_timer.setInterval(60 * 60 * 1000)
        self._common_apps_timer.timeout.connect(self._sample_common_apps_usage)
        # Start the timer; the first tick will occur after the interval.
        self._common_apps_timer.start()

    def on_open_output_messages(self) -> None:
        """Open the Output Messages dialog for toggling log categories."""

        dlg = OutputMessagesDialog(api_port=self.api_port, parent=self)
        dlg.exec()

    def on_open_time_settings(self) -> None:
        """Open the Time / Timezone settings dialog."""

        dlg = TimeSettingsDialog(api_port=self.api_port, parent=self)
        dlg.exec()
        # After closing the dialog, refresh the status bar TZ label
        self.refresh_timezone_in_statusbar()

    def on_shutdown_api(self) -> None:
        """Shut down the API and close the GUI.

        This effectively stops the entire DisplayPad Server process.
        """

        resp = QMessageBox.question(
            self,
            "Shut Down API",
            "This will shut down the DisplayPad Server API and close the GUI.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        app = QApplication.instance()
        if app is not None:
            app.quit()

    def on_restart_api(self) -> None:
        """Restart the API and GUI by re-launching the current Python process."""

        resp = QMessageBox.question(
            self,
            "Restart API",
            "This will restart the DisplayPad Server API and GUI.\n\n"
            "Any in-progress operations will be interrupted. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        python_exe = sys.executable
        script_path = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        try:
            subprocess.Popen([python_exe, script_path, *args], cwd=os.getcwd())
        except Exception as e:
            QMessageBox.critical(self, "Restart API", f"Failed to restart server: {e}")
            return

        app = QApplication.instance()
        if app is not None:
            app.quit()

    def setup_ui(self):
        # Menu bar with server controls and Application Library integration hooks
        menubar = self.menuBar()

        # Server menu for controlling the API / GUI process
        server_menu = menubar.addMenu("Server")
        self.action_restart_api = server_menu.addAction("Restart API")
        self.action_restart_api.triggered.connect(self.on_restart_api)

        self.action_shutdown_api = server_menu.addAction("Shut Down API")
        self.action_shutdown_api.triggered.connect(self.on_shutdown_api)

        # Settings menu for global server/GUI options
        settings_menu = menubar.addMenu("Settings")
        self.action_output_messages = settings_menu.addAction("Output Messages...")
        self.action_output_messages.triggered.connect(self.on_open_output_messages)
        self.action_time_settings = settings_menu.addAction("Time / Timezone...")
        self.action_time_settings.triggered.connect(self.on_open_time_settings)

        # Applications menu for Application Library features
        applications_menu = menubar.addMenu("Applications")

        self.action_scan_apps = applications_menu.addAction("Scan Installed Applications")
        self.action_scan_apps.triggered.connect(self.on_scan_installed_applications)

        self.action_app_library = applications_menu.addAction("Application Library")
        self.action_app_library.triggered.connect(self.on_open_application_library)

        self.action_add_app_manual = applications_menu.addAction("Add Application Manually")
        self.action_add_app_manual.triggered.connect(self.on_add_application_manually)

        self.action_rescan_db = applications_menu.addAction("Rescan / Refresh Database")
        self.action_rescan_db.triggered.connect(self.on_rescan_application_database)

        self.action_import_app_icons = applications_menu.addAction("Import Program Icons")
        self.action_import_app_icons.triggered.connect(self.on_import_program_icons)

        # Usage statistics view for "common apps" tracking
        self.action_app_usage_stats = applications_menu.addAction("Application Usage Stats")
        self.action_app_usage_stats.triggered.connect(self.on_open_app_usage_stats)

        # Manual trigger to scan currently running applications and bump
        # usage scores immediately, instead of waiting for the hourly timer.
        self.action_scan_running_usage = applications_menu.addAction("Scan Running Applications (Usage)")
        self.action_scan_running_usage.triggered.connect(self.on_scan_running_for_usage)

        # Macro menu for managing reusable macros that can be assigned to
        # keypad buttons.
        macros_menu = menubar.addMenu("Builders")
        self.action_macro_builder = macros_menu.addAction("Macro Builder...")
        self.action_macro_builder.triggered.connect(self.on_open_macro_builder)
        self.action_profile_builder = macros_menu.addAction("Profile Builder...")
        self.action_profile_builder.triggered.connect(self.on_open_profile_builder)

        # Devices menu for per-pad tooling such as viewing raw device logs.
        devices_menu = menubar.addMenu("Devices")
        self.action_device_logs = devices_menu.addAction("View Device Logs for Selected Pad")
        self.action_device_logs.triggered.connect(self.on_open_device_logs)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # Title bar with pairing code
        title_bar = QFrame()
        title_bar.setFixedHeight(96)
        title_bar.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {CYBERPUNK_COLORS["bg_dark"]},
                    stop: 0.45 {CYBERPUNK_COLORS["bg_panel"]},
                    stop: 1 {CYBERPUNK_COLORS["bg_elevated"]}
                );
                border-bottom: 1px solid {CYBERPUNK_COLORS["gothic_primary"]};
            }}
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(24, 16, 24, 16)

        # Logo/Title
        title = QLabel("◈ DISPLAYPAD SERVER")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']}; letter-spacing: 2px;")
        title_layout.addWidget(title)

        title_subtitle = QLabel("Dark mode control center for every connected pad")
        title_subtitle.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_gray']}; font-size: 12px;")
        title_layout.addWidget(title_subtitle)

        title_layout.addStretch()

        # Pairing code display (top right)
        self.pairing_display = PairingCodeDisplay(self.api_port)
        title_layout.addWidget(self.pairing_display)

        layout.addWidget(title_bar)

        # Main content splitter
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left panel - Pad list
        self.pad_list = PadListWidget(self.api_port)
        self.pad_list.pad_selected.connect(self.on_pad_selected)
        self.pad_list.setMinimumWidth(280)
        self.pad_list.setMaximumWidth(350)
        splitter.addWidget(self.pad_list)

        # Right panel - Main area with tabs
        right_panel = QFrame()
        right_panel.setStyleSheet(f"background: {CYBERPUNK_COLORS['bg_dark']};")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(18)

        # Welcome message
        self.welcome_label = QLabel("""
            <h2 style='color: #f5f1fb;'>Welcome to DisplayPad Server</h2>
            <p style='color: #baaecd; font-size: 14px;'>
            Select a keypad from the left panel to configure.<br><br>
            <b>Discovery:</b> Keypads automatically discover this PC on the network and self-register.<br>
            <b>Keypad Types:</b> Task Keypads for productivity, Macro Keypads for automation.<br>
            <b>Configuration:</b> Set up buttons, icons, and actions for each keypad.
            </p>
        """)
        self.welcome_label.setWordWrap(True)
        self.welcome_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.welcome_label.setStyleSheet(f"background: {CYBERPUNK_COLORS['bg_panel']}; border: 1px solid {CYBERPUNK_COLORS['gothic_primary']}35; border-radius: 18px; padding: 18px;")
        right_layout.addWidget(self.welcome_label)

        # Quick actions
        actions_frame = QFrame()
        actions_frame.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}35;
                border-radius: 18px;
                padding: 16px;
            }}
        """)
        actions_layout = QHBoxLayout(actions_frame)
        actions_layout.setSpacing(14)

        self.add_keypad_btn = CyberpunkButton("+ ADD KEYPAD", "green")
        self.add_keypad_btn.setFixedHeight(52)
        self.add_keypad_btn.clicked.connect(self.show_add_keypad)
        actions_layout.addWidget(self.add_keypad_btn)

        self.settings_btn = CyberpunkButton("⚙ SETTINGS", "cyan")
        self.settings_btn.setFixedHeight(52)
        self.settings_btn.clicked.connect(self.show_settings)
        actions_layout.addWidget(self.settings_btn)

        self.help_btn = CyberpunkButton("? HELP", "purple")
        self.help_btn.setFixedHeight(52)
        self.help_btn.clicked.connect(self.show_help)
        actions_layout.addWidget(self.help_btn)

        right_layout.addWidget(actions_frame)
        right_layout.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 900])
        layout.addWidget(splitter)

        # Status bar
        self.refresh_timezone_in_statusbar()
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                color: {CYBERPUNK_COLORS["neon_cyan"]};
                border-top: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
            }}
        """)

    def refresh_timezone_in_statusbar(self) -> None:
        """Update the status bar with current API port and timezone."""

        try:
            resp = requests.get(
                f"http://127.0.0.1:{self.api_port}/api/v1/time/settings",
                timeout=3,
            )
            resp.raise_for_status()
            data = resp.json()
            tz = data.get("timezone", "America/Chicago")
        except Exception:
            tz = "Unknown"

        self.statusBar().showMessage(
            f"DisplayPad Server Ready | API Port: {self.api_port} | TZ: {tz}"
        )

    def apply_cyberpunk_theme(self):
        """Apply Cyberpunk theme to the main window."""
        self.setStyleSheet(f"""
            QMainWindow {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
            }}
            QWidget {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
            }}
            QMenuBar {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                color: {CYBERPUNK_COLORS["text_white"]};
                border-bottom: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}45;
                padding: 6px;
            }}
            QMenuBar::item:selected {{
                background: {CYBERPUNK_COLORS["gothic_primary"]}25;
                border-radius: 8px;
            }}
            QMenu {{
                background: {CYBERPUNK_COLORS["bg_elevated"]};
                color: {CYBERPUNK_COLORS["text_white"]};
                border: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}66;
                padding: 6px;
            }}
            QMenu::item:selected {{
                background: {CYBERPUNK_COLORS["gothic_primary"]}30;
            }}
            QStatusBar {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                color: {CYBERPUNK_COLORS["text_gray"]};
                border-top: 1px solid {CYBERPUNK_COLORS["gothic_primary"]}40;
            }}
        """)

    def on_open_app_usage_stats(self) -> None:
        """Open the Application Usage Statistics window."""

        dlg = CommonAppsStatsWindow(self)
        dlg.exec()

    def on_scan_running_for_usage(self) -> None:
        """Manually sample running apps and update usage statistics now."""

        self._sample_common_apps_usage()
        QMessageBox.information(
            self,
            "Scan Running Applications",
            "Usage statistics have been updated based on currently running applications.",
        )

    def _sample_common_apps_usage(self) -> None:
        """Increment usage_score for applications that are currently running.

        This runs periodically in the background and is best-effort only; any
        failures are logged and otherwise ignored.
        """

        try:
            from displaypad_server.windows.processes import list_running_executables

            running = list_running_executables()
            if not running:
                return

            # Normalise running executable paths to a lowered, resolved form.
            from pathlib import Path as _Path

            norm_running: set[str] = set()
            for p in running:
                if not p:
                    continue
                try:
                    norm_running.add(str(_Path(p).resolve()).lower())
                except Exception:
                    norm_running.add(p.lower())

            if not norm_running:
                return

            cfg = _get_config()
            with _db_connect(cfg.database_path) as conn:
                cur = conn.execute(
                    "SELECT id, executable_path FROM applications WHERE enabled = 1"
                )
                rows = cur.fetchall()

                now_iso = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    exe = row["executable_path"] or ""
                    if not exe:
                        continue
                    try:
                        norm_exe = str(_Path(exe).resolve()).lower()
                    except Exception:
                        norm_exe = exe.lower()

                    if norm_exe in norm_running:
                        conn.execute(
                            "UPDATE applications SET usage_score = usage_score + 1, updated_at = ? WHERE id = ?",
                            (now_iso, row["id"]),
                        )

                conn.commit()
        except Exception as e:  # pragma: no cover - best-effort logging
            print(f"[GUI] _sample_common_apps_usage failed: {e}", flush=True)

    def on_pad_selected(self, pad_data: dict):
        """Handle keypad selection."""
        self.current_pad = pad_data
        dialog = KeypadConfigDialog(pad_data, self.api_port, self)
        dialog.exec()

    def on_open_device_logs(self) -> None:
        initial_pad_uuid: str | None = None
        initial_pad_name: str | None = None
        if self.current_pad:
            pad_uuid = self.current_pad.get("pad_uuid") or ""
            pad_name = self.current_pad.get("name") or pad_uuid
            if pad_uuid:
                initial_pad_uuid = pad_uuid
                initial_pad_name = pad_name
        dialog = DeviceLogWindow(self.api_port, initial_pad_uuid, initial_pad_name, self)
        dialog.exec()

    def on_open_macro_builder(self) -> None:
        """Open the Macro Builder dialog for managing reusable macros."""

        dialog = MacroBuilderDialog(self)
        dialog.exec()

    def on_open_profile_builder(self) -> None:
        dialog = ProfileBuilderDialog(self.api_port, self)
        dialog.exec()


    def show_add_keypad(self):
        """Show info for adding a new keypad (no pairing codes)."""
        QMessageBox.information(
            self,
            "Add Keypad",
            "DisplayPad keypads are added automatically.\n\n"
            "1. Connect the ESP32 to the same network as this PC.\n"
            "2. On boot, the keypad will scan for this host and auto-register.\n"
            "3. When it appears in the list on the left, double-click it to edit its buttons."
        )

    def show_settings(self):
        """Show settings dialog."""
        QMessageBox.information(self, "Settings", "Settings dialog coming soon!")

    def show_help(self):
        """Show help dialog."""
        help_text = """
        <h2 style='color: #00f0ff;'>DisplayPad Server Help</h2>
        <p><b>Pairing:</b> Use the pairing code in the top right corner to pair your ESP32 keypad.</p>
        <p><b>Keypad Types:</b>
        <ul>
        <li><b>Task Keypad:</b> For productivity tasks like media control, shortcuts</li>
        <li><b>Macro Keypad:</b> For complex automation and scripted actions</li>
        </ul></p>
        <p><b>Button Configuration:</b>
        <ul>
        <li>Label: The text shown on the button</li>
        <li>Icon: Visual indicator for the button</li>
        <li>Action Type: What happens when pressed</li>
        <li>Action Details: Specific commands or macros</li>
        </ul></p>
        """
        msg = QMessageBox(self)
        msg.setWindowTitle("Help")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(help_text)
        msg.exec()

    def on_scan_installed_applications(self):
        try:
            from displaypad_server import application_scanner

            stats = application_scanner.scan_installed_applications()
            QMessageBox.information(
                self,
                "Scan Installed Applications",
                "Scan complete.\n\n"
                f"Candidates: {stats.get('total_candidates', 0)}\n"
                f"Added: {stats.get('added', 0)}\n"
                f"Updated: {stats.get('updated', 0)}\n"
                f"Skipped: {stats.get('skipped', 0)}",
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Scan Installed Applications", f"Scanning failed: {e}")

    def on_open_application_library(self):
        dlg = ApplicationLibraryWindow(self)
        dlg.exec()

    def on_add_application_manually(self):
        from displaypad_server import applications as app_repo

        dlg = ApplicationEditDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        data = dlg.get_values()
        try:
            app_repo.create_manual_application(
                name=data["name"],
                executable_path=data["executable_path"],
                working_directory=data["working_directory"],
                arguments=data["arguments"],
                icon_path=data["icon_path"],
                category=data["category"],
                notes=data["notes"],
                enabled=data["enabled"],
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Add Application Manually", f"Failed to save application: {e}")
            return

        QMessageBox.information(
            self,
            "Add Application Manually",
            "Application saved to the library.",
        )

    def on_rescan_application_database(self):
        try:
            from displaypad_server import application_scanner

            stats = application_scanner.scan_installed_applications()
            QMessageBox.information(
                self,
                "Rescan / Refresh Database",
                "Scan complete.\n\n"
                f"Candidates: {stats.get('total_candidates', 0)}\n"
                f"Added: {stats.get('added', 0)}\n"
                f"Updated: {stats.get('updated', 0)}\n"
                f"Skipped: {stats.get('skipped', 0)}",
            )
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Rescan / Refresh Database", f"Scanning failed: {e}")

    def on_import_program_icons(self):
        try:
            from displaypad_server import application_icon_importer

            stats = application_icon_importer.import_program_icons()
            msg = (
                "Import complete.\n\n"
                f"Applications: {stats.get('total_apps', 0)}\n"
                f"Icons created: {stats.get('icons_created', 0)}\n"
                f"Icons updated: {stats.get('icons_updated', 0)}\n"
                f"Skipped: {stats.get('skipped', 0)}\n"
                f"Errors: {stats.get('errors', 0)}"
            )

            error_details = stats.get("error_details") or []
            if error_details:
                # Show a short, human-readable report of which applications
                # failed and why. Limit the number of lines to avoid an
                # overwhelming dialog.
                max_lines = 20
                lines = []
                for detail in error_details[:max_lines]:
                    lines.append(f"- {detail}")
                if len(error_details) > max_lines:
                    remaining = len(error_details) - max_lines
                    lines.append(f"... and {remaining} more error(s).")

                msg += "\n\nError details:\n" + "\n".join(lines)

            QMessageBox.information(self, "Import Program Icons", msg)
        except Exception as e:  # pragma: no cover - best-effort logging
            QMessageBox.critical(self, "Import Program Icons", f"Import failed: {e}")


class SystemTrayApp:
    """System tray application that can launch the GUI."""

    def __init__(self, api_port: int = 7443):
        print("[SystemTrayApp] Initializing system tray app...", flush=True)
        self.api_port = api_port
        self.app = QApplication(sys.argv)
        self.app.setStyle("Fusion")
        self.app.setQuitOnLastWindowClosed(False)  # Keep running when window closed

        # Set application-wide font
        font = QFont("Segoe UI", 10)
        font.setStyleHint(QFont.StyleHint.SansSerif)
        self.app.setFont(font)

        # Create system tray icon
        self.tray_icon = QSystemTrayIcon(self.app)

        # Create icon (use a simple colored circle if no icon file)
        icon = self.create_tray_icon()
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("DisplayPad Server - Right-click for menu")

        # Create context menu
        self.create_context_menu()

        # Connect activated signal (left click)
        self.tray_icon.activated.connect(self.on_tray_activated)

        # Show the tray icon
        self.tray_icon.show()

        # Hidden session watcher so pads respond to Windows lock/unlock even
        # if the main window is never opened.
        if sys.platform == "win32":
            try:
                self._session_watcher = SessionStateWatcher(self.api_port, parent=None)
            except Exception:
                self._session_watcher = None
        else:
            self._session_watcher = None

        print("[SystemTrayApp] Initialization complete; entering event loop soon", flush=True)

    def create_tray_icon(self):
        """Create a simple icon for the system tray."""
        from PyQt6.QtGui import QPixmap, QPainter, QColor, QBrush

        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor("transparent"))

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Draw cyan circle background
        painter.setBrush(QBrush(QColor(CYBERPUNK_COLORS["neon_cyan"])))
        painter.setPen(QColor(CYBERPUNK_COLORS["neon_cyan"]))
        painter.drawEllipse(4, 4, 56, 56)

        # Draw inner dark circle
        painter.setBrush(QBrush(QColor(CYBERPUNK_COLORS["bg_dark"])))
        painter.setPen(QColor(CYBERPUNK_COLORS["bg_dark"]))
        painter.drawEllipse(12, 12, 40, 40)

        # Draw DP text
        painter.setPen(QColor(CYBERPUNK_COLORS["neon_cyan"]))
        font = QFont("Segoe UI", 16, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "DP")

        painter.end()

        return QIcon(pixmap)

    def create_context_menu(self):
        """Create right-click context menu."""
        menu = QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 5px;
            }}
            QMenu::item {{
                padding: 8px 20px;
                background: transparent;
            }}
            QMenu::item:selected {{
                background: {CYBERPUNK_COLORS["neon_cyan"]}30;
                color: {CYBERPUNK_COLORS["neon_cyan"]};
            }}
            QMenu::separator {{
                height: 1px;
                background: {CYBERPUNK_COLORS["neon_cyan"]}40;
                margin: 5px 0px;
            }}
        """)

        # Open GUI action
        open_action = QAction("Open GUI", self.app)
        open_action.triggered.connect(self.open_gui)
        menu.addAction(open_action)

        # Restart Server action
        restart_action = QAction("Restart Server", self.app)
        restart_action.triggered.connect(self.on_restart_server_from_tray)
        menu.addAction(restart_action)

        # Refresh Pads action
        refresh_action = QAction("Refresh Pads", self.app)
        refresh_action.triggered.connect(self.on_refresh_pads_from_tray)
        menu.addAction(refresh_action)

        menu.addSeparator()

        # Exit action
        exit_action = QAction("Exit", self.app)
        exit_action.triggered.connect(self.quit)
        menu.addAction(exit_action)

        self.tray_icon.setContextMenu(menu)

    def on_tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.open_gui()

    def open_gui(self):
        """Open the main GUI window."""
        # Check if window already exists
        if hasattr(self, 'main_window') and self.main_window.isVisible():
            self.main_window.raise_()
            self.main_window.activateWindow()
            return

        # Create and show main window
        self.main_window = DisplayPadMainWindow(self.api_port)

        # Connect close button to hide instead of quit
        self.main_window.closeEvent = self.on_main_window_close

        self.main_window.show()

    def on_main_window_close(self, event):
        """Handle main window close - hide to tray instead of quitting."""
        self.main_window.hide()
        event.ignore()  # Don't actually close

        # Show notification
        self.tray_icon.showMessage(
            "DisplayPad Server",
            "GUI minimized to system tray. Right-click icon to reopen.",
            QSystemTrayIcon.MessageIcon.Information,
            2000
        )

    def quit(self):
        """Quit the application."""
        self.tray_icon.hide()
        self.app.quit()

    def run(self):
        """Run the application."""
        print("[SystemTrayApp] Calling app.exec()", flush=True)
        code = self.app.exec()
        print(f"[SystemTrayApp] app.exec() returned {code}", flush=True)
        sys.exit(code)

    def on_restart_server_from_tray(self) -> None:
        """Restart the DisplayPad Server (API + GUI) from the tray menu."""

        resp = QMessageBox.question(
            None,
            "Restart Server",
            "This will restart the DisplayPad Server API and GUI.\n\n"
            "Any in-progress operations will be interrupted. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if resp != QMessageBox.StandardButton.Yes:
            return

        python_exe = sys.executable
        script_path = os.path.abspath(sys.argv[0])
        args = sys.argv[1:]

        try:
            subprocess.Popen([python_exe, script_path, *args], cwd=os.getcwd())
        except Exception as e:
            QMessageBox.critical(None, "Restart Server", f"Failed to restart server: {e}")
            return

        self.quit()

    def on_refresh_pads_from_tray(self) -> None:
        """Trigger a refresh of pad assignments via the API."""

        try:
            url = f"http://127.0.0.1:{self.api_port}/api/v1/discovery/pads/refresh"
            resp = requests.post(url, timeout=5)
        except Exception as e:
            QMessageBox.critical(None, "Refresh Pads", f"Failed to contact API: {e}")
            return

        if not resp.ok:
            QMessageBox.warning(None, "Refresh Pads", f"API returned HTTP {resp.status_code}")
            return

        try:
            data = resp.json()
        except Exception:
            data = {}

        refreshed = data.get("refreshed", 0)
        total = data.get("total", 0)
        QMessageBox.information(
            None,
            "Refresh Pads",
            f"Refresh request sent.\n\nPads processed: {total}\nAssignments sent: {refreshed}",
        )


def start_gui(api_port: int = 7443):
    """Start the DisplayPad Server GUI with system tray."""
    tray_app = SystemTrayApp(api_port)
    tray_app.run()


def start_gui_window_only(api_port: int = 7443):
    """Start only the GUI window without system tray (legacy mode)."""
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Set application-wide font
    font = QFont("Segoe UI", 10)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    app.setFont(font)

    # Create and show main window
    window = DisplayPadMainWindow(api_port)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    start_gui()
