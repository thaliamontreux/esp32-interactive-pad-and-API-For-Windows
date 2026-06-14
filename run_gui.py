#!/usr/bin/env python3
"""DisplayPad Server with Cyberpunk GUI."""

import sys
import threading
import time
from pathlib import Path

# Add src to path
src_path = Path(__file__).resolve().parent / "src"
sys.path.insert(0, str(src_path))

import uvicorn
from displaypad_server.core.config import get_config, get_api_identity
from displaypad_server.db.database import initialize_database
from displaypad_server.main import create_app
from displaypad_server.api.pairing import start_auto_rotation
from displaypad_server.windows.gui import start_gui

# Global shutdown flag
shutdown_requested = False


def run_api_server(port: int):
    """Run the API server in a thread."""
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def main():
    """Main entry point - starts both API server and GUI."""
    # Get configuration
    config = get_config()

    # Initialize database
    print(f"Initializing database at {config.database_path}")
    initialize_database(config.database_path)

    # Ensure API identity exists
    identity = get_api_identity(config.database_path)
    print(f"API UUID: {identity.api_uuid}")

    # Start auto-rotation of pairing codes (300s = 5 minutes)
    start_auto_rotation()

    # Start API server in background thread
    print(f"Starting API server on port {config.api_port}")
    api_thread = threading.Thread(
        target=run_api_server,
        args=(config.api_port,),
        daemon=True
    )
    api_thread.start()

    # Wait for API to start
    time.sleep(2)

    # Start GUI (blocks until closed)
    print("Starting DisplayPad GUI...")
    start_gui(config.api_port)


if __name__ == "__main__":
    main()
