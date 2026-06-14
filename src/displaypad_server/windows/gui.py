"""DisplayPad Server Windows GUI with Cyberpunk theme."""

import os
import sys
import time
import subprocess
from datetime import datetime, timezone
import requests
from datetime import datetime, timedelta
from typing import Optional

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
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread, QSize, QObject
from PyQt6.QtGui import QFont, QIcon, QColor, QPalette, QLinearGradient, QGradient, QBrush, QPixmap, QPainter, QPen, QAction

from displaypad_server.core.config import get_config as _get_config
from displaypad_server.db.database import connect as _db_connect

# Cyberpunk Color Scheme
CYBERPUNK_COLORS = {
    "bg_dark": "#0a0a0f",
    "bg_panel": "#12121a",
    "neon_cyan": "#00f0ff",
    "neon_pink": "#ff00ff",
    "neon_yellow": "#ffff00",
    "neon_green": "#00ff41",
    "neon_red": "#ff0040",
    "neon_purple": "#b026ff",
    "text_white": "#ffffff",
    "text_gray": "#a0a0a0",
    "border_glow": "#00f0ff",
}


class _MacroEventBus(QObject):
    macros_changed = pyqtSignal()


MACRO_EVENT_BUS = _MacroEventBus()


class CyberpunkButton(QPushButton):
    """3D Cyberpunk styled button."""

    def __init__(self, text: str, color: str = "cyan", parent=None):
        super().__init__(text, parent)
        self.color_name = color
        self.color = CYBERPUNK_COLORS.get(f"neon_{color}", CYBERPUNK_COLORS["neon_cyan"])
        self.setFixedHeight(45)
        self.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_style()

    def update_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self.color}40,
                    stop: 0.5 {self.color}20,
                    stop: 1 {self.color}10
                );
                border: 2px solid {self.color};
                border-radius: 8px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 8px 20px;
                text-transform: uppercase;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self.color}60,
                    stop: 0.5 {self.color}40,
                    stop: 1 {self.color}20
                );
                border: 2px solid {self.color};
                box-shadow: 0 0 15px {self.color};
            }}
            QPushButton:pressed {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {self.color}80,
                    stop: 0.5 {self.color}60,
                    stop: 1 {self.color}40
                );
            }}
        """)
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
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 8px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # Header
        # Discovered Pads Section
        discovered_header = QLabel("DISCOVERED PADS")
        discovered_header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_pink']}; font-size: 11px; font-weight: bold;")
        discovered_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(discovered_header)

        self.discovered_list = QListWidget()
        self.discovered_list.setMaximumHeight(100)
        self.discovered_list.setStyleSheet(f"""
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_pink"]}30;
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
            QListWidget::item {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_pink"]}20;
                border-radius: 4px;
                padding: 6px;
                margin: 2px 0px;
            }}
        """)
        self.discovered_list.itemDoubleClicked.connect(self.add_discovered_pad)
        layout.addWidget(self.discovered_list)

        # Connected Keypads Section
        header = QLabel("CONNECTED KEYPADS")
        header.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; font-size: 12px; font-weight: bold;")
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(header)

        # List
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: none;
                color: {CYBERPUNK_COLORS["text_white"]};
            }}
            QListWidget::item {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}30;
                border-radius: 4px;
                padding: 10px;
                margin: 4px 0px;
            }}
            QListWidget::item:hover {{
                background: {CYBERPUNK_COLORS["neon_cyan"]}20;
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
            QListWidget::item:selected {{
                background: {CYBERPUNK_COLORS["neon_cyan"]}30;
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
        """)
        self.list_widget.itemClicked.connect(self.on_pad_selected)
        layout.addWidget(self.list_widget)

        # Refresh button
        self.refresh_btn = CyberpunkButton("REFRESH", "green")
        self.refresh_btn.setFixedHeight(35)
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

    def __init__(self, slot: int, parent=None):
        super().__init__(parent)
        self.slot = slot
        self._app_records: list | None = None
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_purple"]}80;
                border-radius: 10px;
                padding: 12px;
            }}
        """)

        # Slightly taller/wider tiles for better readability on large layouts.
        self.setMinimumSize(285, 285)
        self.setMaximumSize(285, 285)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 14, 14, 14)

        # Slot label
        slot_label = QLabel(f"BUTTON {self.slot}")
        slot_label.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_purple']}; font-size: 10px; font-weight: bold;")
        layout.addWidget(slot_label)

        # Label input
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("Button Label")
        self.label_input.setStyleSheet(f"""
            QLineEdit {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 4px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
            }}
        """)
        self.label_input.setMaxLength(16)

        label_row = QHBoxLayout()
        label_row.addWidget(self.label_input)

        self.show_text_checkbox = QCheckBox("Show text")
        self.show_text_checkbox.setChecked(True)
        self.show_text_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']}; font-size: 10px;")
        label_row.addWidget(self.show_text_checkbox)

        layout.addLayout(label_row)

        # Shared combo-box style for action/app/icon fields
        combo_style = f"""
            QComboBox {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 4px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
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
        self.action_details.setMaximumHeight(80)
        self.action_details.setStyleSheet(f"""
            QTextEdit {{
                background: {CYBERPUNK_COLORS["bg_dark"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 4px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 6px;
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

        layout.addLayout(color_row)

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
        if icon_id:
            idx = self.icon_combo.findText(icon_id, Qt.MatchFlag.MatchFixedString)
            if idx >= 0:
                self.icon_combo.setCurrentIndex(idx)

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
            if macro_action_id is not None:
                idx = self.macro_combo.findData(macro_action_id)
                if idx >= 0:
                    self.macro_combo.setCurrentIndex(idx)

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
        type_layout.addWidget(self.time_format_combo)

        self.ampm_checkbox = QCheckBox("Show AM/PM")
        self.ampm_checkbox.setChecked(True)
        self.ampm_checkbox.setStyleSheet(f"color: {CYBERPUNK_COLORS['text_white']};")
        type_layout.addWidget(self.ampm_checkbox)

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

        self.buttons_container = QWidget()
        self.buttons_grid = QGridLayout(self.buttons_container)
        # More generous spacing between tiles for readability on large layouts.
        self.buttons_grid.setHorizontalSpacing(10)
        self.buttons_grid.setVerticalSpacing(12)

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
            page_widgets.append(w)

        if len(page_widgets) > count:
            # Keep extra widgets in memory but don't display them
            page_widgets[:] = page_widgets[:count]

        self.button_configs = page_widgets

        self._relayout_buttons()

    def _on_button_count_changed(self, text: str) -> None:
        """Update button count for the current page and rebuild its widgets."""
        try:
            count = int(text)
        except ValueError:
            return

        page = self.current_page
        self.page_button_counts[page] = count
        self._create_button_widgets(count)

    def _relayout_buttons(self) -> None:
        if not hasattr(self, "button_configs") or not self.button_configs:
            return

        while self.buttons_grid.count():
            item = self.buttons_grid.takeAt(0)
            # Do not change widget parent; widgets remain owned by buttons_container

        tile_width = 275
        spacing = 3

        if hasattr(self, "scroll_area") and self.scroll_area is not None:
            available_width = self.scroll_area.viewport().width()
        else:
            available_width = self.width()

        if available_width <= 0:
            available_width = self.width()

        cols = max(1, (available_width + spacing) // (tile_width + spacing))

        for i, btn_config in enumerate(self.button_configs):
            self._populate_icon_combo(btn_config)
            self._populate_macro_combo(btn_config)
            row = i // cols
            col = i % cols
            self.buttons_grid.addWidget(btn_config, row, col)

        # Ensure the per-button UI matches the current keypad mode
        self._apply_mode_to_button_widgets()

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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout_buttons()

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
            QPushButton {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["neon_cyan"]}40,
                    stop: 0.5 {CYBERPUNK_COLORS["neon_cyan"]}20,
                    stop: 1 {CYBERPUNK_COLORS["neon_cyan"]}10
                );
                border: 2px solid {CYBERPUNK_COLORS["neon_cyan"]};
                border-radius: 6px;
                color: {CYBERPUNK_COLORS["text_white"]};
                padding: 8px 20px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 0, y2: 1,
                    stop: 0 {CYBERPUNK_COLORS["neon_cyan"]}60,
                    stop: 0.5 {CYBERPUNK_COLORS["neon_cyan"]}40,
                    stop: 1 {CYBERPUNK_COLORS["neon_cyan"]}20
                );
            }}
        """)

    def save_config(self):
        """Save the keypad configuration."""
        # Collect button configs across all pages
        all_buttons: list[dict] = []
        for page, widgets in self.all_button_widgets.items():
            for btn in widgets:
                cfg = btn.get_config()
                cfg["page"] = page
                all_buttons.append(cfg)

        # Determine total pages and per-page button counts
        total_pages = self.page_count_combo.currentIndex() + 1
        page_counts: list[int] = []
        for p in range(1, total_pages + 1):
            count = self.page_button_counts.get(p)
            if count is None:
                # Fallback to current combo selection or default 6
                try:
                    count = int(self.button_count_combo.currentText())
                except ValueError:
                    count = 6
            page_counts.append(max(1, min(32, int(count))))

        config = {
            "pad_uuid": self.pad_data.get("pad_uuid"),
            "type": "task" if self.task_radio.isChecked() else "macro",
            "buttons": all_buttons,
            # Backwards-compatible: keep a single button_count (page 1)
            "button_count": page_counts[0] if page_counts else 6,
            "page_count": total_pages,
            "page_button_counts": page_counts,
        }

        # Per-pad time configuration
        config["time_use_24h"] = self.time_format_combo.currentIndex() == 1
        config["time_show_am_pm"] = self.ampm_checkbox.isChecked()

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

            # Set mode
            mode = data.get("pad_mode", "macro_keypad")
            self.task_radio.setChecked(mode == "task_keypad")
            self.macro_radio.setChecked(mode == "macro_keypad")

            # Time configuration (fall back to defaults if not present)
            time_cfg = data.get("time") or {}
            use_24h = bool(time_cfg.get("use_24h", False))
            show_am_pm = bool(time_cfg.get("show_am_pm", True))

            self.time_format_combo.setCurrentIndex(1 if use_24h else 0)
            self.ampm_checkbox.setChecked(show_am_pm)

            # Map buttons by (page, slot) for lookup
            buttons = data.get("buttons", [])
            btn_by_page_slot: dict[tuple[int, int], dict] = {}
            for b in buttons:
                page = int(b.get("page", 1) or 1)
                slot = int(b.get("slot", 0) or 0)
                if slot > 0:
                    btn_by_page_slot[(page, slot)] = b

            # Restore page_count and per-page button counts if present
            api_page_count = int(data.get("page_count", 1) or 1)
            api_page_counts = data.get("page_button_counts") or []
            allowed = [6, 8, 10, 12, 16, 20, 24, 28, 32]

            # Normalize API page_counts to allowed values
            page_counts: list[int] = []
            for i in range(api_page_count):
                if i < len(api_page_counts):
                    try:
                        c = int(api_page_counts[i])
                    except (TypeError, ValueError):
                        c = 6
                else:
                    c = 6
                # Snap to nearest allowed button count
                c = min(allowed, key=lambda n: abs(n - c))
                page_counts.append(c)

            if not page_counts:
                page_counts = [6]

            # Update internal structures and UI controls
            self.page_button_counts.clear()
            for i, c in enumerate(page_counts, start=1):
                self.page_button_counts[i] = c

            total_pages = min(len(page_counts), 4)
            self.page_count_combo.blockSignals(True)
            self.page_count_combo.setCurrentIndex(total_pages - 1)
            self.page_count_combo.blockSignals(False)

            # Rebuild page selector based on total_pages
            self.page_combo.blockSignals(True)
            self.page_combo.clear()
            for p in range(1, total_pages + 1):
                self.page_combo.addItem(str(p))
            self.page_combo.blockSignals(False)

            # Initialize widgets for all pages present in data
            self.all_button_widgets.clear()
            self.current_page = 1
            self.button_count_combo.blockSignals(True)
            self.button_count_combo.setCurrentText(str(page_counts[0]))
            self.button_count_combo.blockSignals(False)
            self._create_button_widgets(page_counts[0])

            for page_index in range(1, total_pages + 1):
                self.current_page = page_index
                count = self.page_button_counts.get(page_index, page_counts[min(page_index - 1, len(page_counts) - 1)])
                self._create_button_widgets(count)
                for widget in self.button_configs:
                    cfg = btn_by_page_slot.get((page_index, widget.slot))
                    if cfg:
                        # If this button references a macro action_id, map it
                        # back to a high-level "Macro" action type and record
                        # the macro_action_id for the widget.
                        action_id = cfg.get("action_id") or ""
                        if action_id and hasattr(self, "_macro_by_action_id") and action_id in self._macro_by_action_id:
                            cfg["action_type"] = "Macro"
                            cfg["macro_action_id"] = action_id
                        elif cfg.get("action_id"):
                            cfg.setdefault("action_type", cfg.get("action_id"))
                        icon_id = cfg.get("icon_id") or ""
                        has_icon = icon_id in self.available_icons
                        print(
                            f"[GUI] restore page={page_index} slot={widget.slot} "
                            f"label={cfg.get('label', '')!r} icon_id={icon_id!r} "
                            f"icon_in_list={has_icon}",
                            flush=True,
                        )
                        widget.set_config(cfg)

            # Restore to page 1 in UI
            self.current_page = 1
            self.page_combo.setCurrentIndex(0)
            first_count = self.page_button_counts.get(1, page_counts[0])
            self.button_count_combo.blockSignals(True)
            self.button_count_combo.setCurrentText(str(first_count))
            self.button_count_combo.blockSignals(False)
            self._create_button_widgets(first_count)

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


class AddStepDialog(QDialog):
    """Dialog that captures keystrokes for a single macro step.

    Keys are recorded as a comma-separated list of tokens (e.g.
    "ALT, CTRL, F"). The user edits using on-screen Backspace and Clear
    buttons so that physical Backspace is treated as a real key event
    instead of editing the text field.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Step")
        self._keys: list[str] = []
        self._build_ui()

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

    def _key_to_token(self, event) -> str | None:
        key = event.key()

        # Handle a few common special keys explicitly for readability.
        if key == Qt.Key.Key_Backspace:
            return "backspace"
        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            return "enter"
        if key == Qt.Key.Key_Tab:
            return "tab"
        if key == Qt.Key.Key_Space:
            return "space"
        if key == Qt.Key.Key_Escape:
            return "escape"
        if key == Qt.Key.Key_Shift:
            return "shift"
        if key == Qt.Key.Key_Control:
            return "ctrl"
        if key == Qt.Key.Key_Alt:
            return "alt"
        if key == Qt.Key.Key_Meta:
            return "meta"

        text = event.text() or ""
        if text:
            return text.upper()

        # Fallback: ignore keys we cannot represent cleanly.
        return None

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        key = event.key()

        # Enter/Return confirms if we have at least one key.
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._keys:
                self.accept()
            return

        # Esc cancels.
        if key == Qt.Key.Key_Escape:
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
        right.addWidget(self.table, 1)

        step_btn_row = QHBoxLayout()
        self.add_step_btn = QPushButton("Add Step")
        self.add_step_btn.clicked.connect(self.on_add_step)
        step_btn_row.addWidget(self.add_step_btn)

        self.remove_step_btn = QPushButton("Remove Step")
        self.remove_step_btn.clicked.connect(self.on_remove_step)
        step_btn_row.addWidget(self.remove_step_btn)
        step_btn_row.addStretch()
        right.addLayout(step_btn_row)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        button_box.accepted.connect(self.on_save_macro)
        button_box.rejected.connect(self.reject)
        right.addWidget(button_box)

        layout.addLayout(right, 2)

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

        self._macros.clear()
        self.list_widget.clear()
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
            self._macros.append(rec)
            item = QListWidgetItem(rec["name"])
            item.setData(Qt.ItemDataRole.UserRole, rec["action_id"])
            self.list_widget.addItem(item)

        if self._macros:
            self.list_widget.setCurrentRow(0)

    def _find_macro_by_action_id(self, action_id: str) -> dict | None:
        for rec in self._macros:
            if rec["action_id"] == action_id:
                return rec
        return None

    # --- UI actions ----------------------------------------------------

    def on_macro_selected(self, row: int) -> None:
        if self._suppress_selection_change:
            return
        if row < 0 or row >= len(self._macros):
            self._current_macro = None
            self.name_edit.clear()
            self.table.clearContents()
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

            self.table.setItem(row, 0, QTableWidgetItem(keys_text))
            self.table.setItem(row, 1, QTableWidgetItem(str(delay_sec)))

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
        dlg = AddStepDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        keys_text = (dlg.get_step_text() or "").strip()
        if not keys_text:
            return

        self.table.setItem(empty_row, 0, QTableWidgetItem(keys_text))
        # Default delay to 0 seconds if not already set for this row.
        if self.table.item(empty_row, 1) is None:
            self.table.setItem(empty_row, 1, QTableWidgetItem("0"))

    def on_remove_step(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)

    def on_save_macro(self) -> None:
        name = (self.name_edit.text() or "").strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Macro name is required.")
            return

        records: list[dict] = []
        rows = min(self.table.rowCount(), self.MAX_STEPS)
        for row in range(rows):
            item_keys = self.table.item(row, 0)
            item_delay = self.table.item(row, 1)
            keys_text = item_keys.text().strip() if item_keys and item_keys.text() else ""
            delay_text = item_delay.text().strip() if item_delay and item_delay.text() else "0"

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
        self.setWindowTitle("DisplayPad Server - Cyberpunk Edition")
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
        macros_menu = menubar.addMenu("Macros")
        self.action_macro_builder = macros_menu.addAction("Macro Builder...")
        self.action_macro_builder.triggered.connect(self.on_open_macro_builder)

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
        title_bar.setFixedHeight(80)
        title_bar.setStyleSheet(f"""
            QFrame {{
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {CYBERPUNK_COLORS["bg_dark"]},
                    stop: 0.5 {CYBERPUNK_COLORS["bg_panel"]},
                    stop: 1 {CYBERPUNK_COLORS["bg_dark"]}
                );
                border-bottom: 2px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(20, 10, 20, 10)

        # Logo/Title
        title = QLabel("◈ DISPLAYPAD SERVER")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {CYBERPUNK_COLORS['neon_cyan']}; letter-spacing: 2px;")
        title_layout.addWidget(title)

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
        right_layout.setContentsMargins(20, 20, 20, 20)

        # Welcome message
        self.welcome_label = QLabel("""
            <h2 style='color: #00f0ff;'>Welcome to DisplayPad Server</h2>
            <p style='color: #a0a0a0; font-size: 14px;'>
            Select a keypad from the left panel to configure.<br><br>
            <b>Discovery:</b> Keypads automatically discover this PC on the network and self-register.<br>
            <b>Keypad Types:</b> Task Keypads for productivity, Macro Keypads for automation.<br>
            <b>Configuration:</b> Set up buttons, icons, and actions for each keypad.
            </p>
        """)
        self.welcome_label.setWordWrap(True)
        self.welcome_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        right_layout.addWidget(self.welcome_label)

        # Quick actions
        actions_frame = QFrame()
        actions_frame.setStyleSheet(f"""
            QFrame {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
                border-radius: 8px;
                padding: 15px;
            }}
        """)
        actions_layout = QHBoxLayout(actions_frame)

        self.add_keypad_btn = CyberpunkButton("+ ADD KEYPAD", "green")
        self.add_keypad_btn.setFixedHeight(40)
        self.add_keypad_btn.clicked.connect(self.show_add_keypad)
        actions_layout.addWidget(self.add_keypad_btn)

        self.settings_btn = CyberpunkButton("⚙ SETTINGS", "cyan")
        self.settings_btn.setFixedHeight(40)
        self.settings_btn.clicked.connect(self.show_settings)
        actions_layout.addWidget(self.settings_btn)

        self.help_btn = CyberpunkButton("? HELP", "purple")
        self.help_btn.setFixedHeight(40)
        self.help_btn.clicked.connect(self.show_help)
        actions_layout.addWidget(self.help_btn)

        right_layout.addWidget(actions_frame)
        right_layout.addStretch()

        splitter.addWidget(right_panel)
        splitter.setSizes([300, 900])
        layout.addWidget(splitter)

        # Status bar
        self.statusBar().showMessage("DisplayPad Server Ready | API Port: " + str(self.api_port))
        self.statusBar().setStyleSheet(f"""
            QStatusBar {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                color: {CYBERPUNK_COLORS["neon_cyan"]};
                border-top: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
            }}
        """)

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
                border-bottom: 1px solid {CYBERPUNK_COLORS["neon_cyan"]}40;
            }}
            QMenuBar::item:selected {{
                background: {CYBERPUNK_COLORS["neon_cyan"]}40;
            }}
            QMenu {{
                background: {CYBERPUNK_COLORS["bg_panel"]};
                color: {CYBERPUNK_COLORS["text_white"]};
                border: 1px solid {CYBERPUNK_COLORS["neon_cyan"]};
            }}
            QMenu::item:selected {{
                background: {CYBERPUNK_COLORS["neon_cyan"]}40;
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

        # Optional: Show notification on startup

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
        sys.exit(self.app.exec())

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
