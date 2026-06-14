# Phase 1 Prompt

Implement the initial Python project skeleton.

Requirements:

1. Create a FastAPI app in `src/displaypad_server/main.py`.
2. Add a health endpoint `/health`.
3. Add SQLite database initialization using schema from `docs/database/SCHEMA.md`.
4. Add app config in `src/displaypad_server/core/config.py`.
5. Add logging setup in `src/displaypad_server/core/logging_config.py`.
6. Add placeholder route modules:
   - pairing
   - pads
   - buttons
   - macros
   - tasks
   - websocket
7. Add a tray placeholder in `src/displaypad_server/windows/tray.py`.
8. Add tests for health endpoint and database initialization.
9. Keep code typed and clean.
