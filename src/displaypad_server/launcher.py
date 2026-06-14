"""DisplayPad Server launcher - starts API server and full GUI."""

import signal
import sys
import threading
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from displaypad_server.core.config import get_config
from displaypad_server.db.database import initialize_database
from displaypad_server.main import create_app

# Global references
api_thread: threading.Thread | None = None
shutdown_event = threading.Event()


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("\nShutting down DisplayPad Server...")
    shutdown_event.set()
    sys.exit(0)


def run_api_server(config) -> None:
    """Run the FastAPI server in a thread."""
    app = create_app()
    uvicorn.run(
        app,
        host=config.api_host,
        port=config.api_port,
        log_level="info",
    )


def main() -> None:
    """Main entry point - starts API server and GUI with system tray."""
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Get configuration
    config = get_config()

    # Initialize database
    print(f"Initializing database at {config.database_path}")
    initialize_database(config.database_path)

    # Ensure API identity exists
    from displaypad_server.core.config import get_api_identity
    identity = get_api_identity(config.database_path)
    print(f"API UUID: {identity.api_uuid}")

    # Start auto-rotation of pairing codes (300s = 5 minutes)
    from displaypad_server.api.pairing import start_auto_rotation
    start_auto_rotation()

    # Start API server in background thread
    print(f"Starting API server on {config.api_host}:{config.api_port}")
    global api_thread
    api_thread = threading.Thread(target=run_api_server, args=(config,), daemon=True)
    api_thread.start()

    # Wait for server to start
    time.sleep(2)

    # Start the full PyQt6 GUI with system tray
    print("Starting DisplayPad GUI...")
    from displaypad_server.windows.gui import start_gui
    start_gui(config.api_port)


if __name__ == "__main__":
    main()
