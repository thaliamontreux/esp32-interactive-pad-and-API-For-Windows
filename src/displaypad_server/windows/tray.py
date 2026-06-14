"""Windows system tray application for DisplayPad Server."""

import threading
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

from displaypad_server.core.config import get_config
from displaypad_server.db.database import initialize_database


# Global reference to tray icon
tray_icon: pystray.Icon | None = None


def _create_icon() -> Image.Image:
    """Create a simple icon for the system tray."""
    # Create a simple colored square icon
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), color=(0, 120, 212))
    dc = ImageDraw.Draw(image)

    # Draw a simple pad-like shape
    dc.rectangle([8, 8, 56, 56], fill=(255, 255, 255), outline=(0, 0, 0), width=2)
    dc.rectangle([16, 16, 48, 32], fill=(200, 200, 200))
    dc.rectangle([16, 36, 48, 52], fill=(200, 200, 200))

    return image


def _open_dashboard() -> None:
    """Open the web dashboard."""
    config = get_config()
    url = f"http://localhost:{config.api_port}/"
    webbrowser.open(url)


def _add_keypad_info() -> None:
    """Explain how new keypads are added via auto-discovery."""
    if tray_icon:
        tray_icon.notify(
            "To add a new keypad:\n"
            "1. Connect the ESP32 DisplayPad to the same network as this PC.\n"
            "2. On boot, it will automatically discover and register with the server.\n"
            "3. Open the GUI to configure its buttons."
        )


def _show_paired_keypads() -> None:
    """Show paired keypads in dashboard."""
    _open_dashboard()


def _show_button_pads() -> None:
    """Show button pads in dashboard."""
    _open_dashboard()


def _show_task_pads() -> None:
    """Show task pads in dashboard."""
    _open_dashboard()


def _show_security() -> None:
    """Show security settings in dashboard."""
    _open_dashboard()


def _show_logs() -> None:
    """Show logs in dashboard."""
    _open_dashboard()


def _restart_api() -> None:
    """Restart the API server."""
    if tray_icon:
        tray_icon.notify("Restart API not implemented yet")


def _exit_tray(icon: pystray.Icon) -> None:
    """Exit the tray application."""
    icon.stop()


def create_menu() -> pystray.Menu:
    """Create the system tray menu."""
    return pystray.Menu(
        pystray.MenuItem("Open Dashboard", lambda: _open_dashboard()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Add New Keypad", lambda: _add_keypad_info()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Paired Keypads", lambda: _show_paired_keypads()),
        pystray.MenuItem("Button Pads", lambda: _show_button_pads()),
        pystray.MenuItem("Task Pads", lambda: _show_task_pads()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Security", lambda: _show_security()),
        pystray.MenuItem("Logs", lambda: _show_logs()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart API", lambda: _restart_api()),
        pystray.MenuItem("Exit", _exit_tray),
    )


def start_tray(stop_event: threading.Event | None = None) -> None:
    """Start the system tray icon."""
    global tray_icon

    try:
        print("[Tray] Creating icon...")
        icon_image = _create_icon()
        print("[Tray] Icon created successfully")

        tray_icon = pystray.Icon(
            "displaypad",
            icon_image,
            "DisplayPad Server",
            menu=create_menu(),
        )
        print("[Tray] Icon object created")

        # Run the icon
        print("[Tray] Starting tray icon...")
        tray_icon.run()
        print("[Tray] Tray stopped")
    except Exception as e:
        print(f"[Tray] Error starting tray: {e}")
        import traceback
        traceback.print_exc()


def stop_tray() -> None:
    """Stop the system tray icon."""
    global tray_icon
    if tray_icon:
        tray_icon.stop()
        tray_icon = None


def start_tray_placeholder() -> None:
    """Placeholder for pystray implementation."""
    print("DisplayPad Server tray placeholder")
