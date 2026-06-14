from pathlib import Path
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from displaypad_server.core.config import get_config
from displaypad_server.db.database import connect

router = APIRouter()


class IconInfo(BaseModel):
    icon_id: str
    source: str | None = None
    updated_at: str | None = None
    url: str


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ESP32_ICONS_HEADER = PROJECT_ROOT / "esp32_icons.h"


def _load_builtin_icon_ids() -> list[str]:
    """Parse esp32_icons.h and return the list of ESP32_ICONS names.

    This keeps the GUI / API icon list in sync with the firmware's
    built-in icon table without relying on the database PNG entries.
    """
    if not ESP32_ICONS_HEADER.exists():
        return []

    try:
        text = ESP32_ICONS_HEADER.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []

    pattern = re.compile(r'^\s*\{"([^\"]+)",\s*\d+,\s*\d+,\s*icon_')
    names: set[str] = set()
    in_table = False

    for line in text.splitlines():
        if not in_table:
            if "static const Esp32Icon ESP32_ICONS[] = {" in line:
                in_table = True
            continue

        # End of the ESP32_ICONS table
        if line.strip().startswith("};"):
            break

        match = pattern.match(line)
        if match:
            names.add(match.group(1))

    return sorted(names)


@router.get("/icons", response_model=list[IconInfo])
def list_icons(request: Request) -> list[IconInfo]:
    """List all registered icons available for ESP32 pads.

    Each icon is identified by its icon_id. The list is derived from the
    esp32_icons.h ESP32_ICONS table so that GUI choices match the firmware's
    built-in icons.
    """
    base_url = str(request.base_url).rstrip("/")

    icons: list[IconInfo] = []
    for icon_id in _load_builtin_icon_ids():
        icons.append(
            IconInfo(
                icon_id=icon_id,
                source="builtin",
                updated_at=None,
                url=f"{base_url}/api/v1/icons/{icon_id}.png",
            )
        )

    return icons


@router.get("/icons/{icon_id}.png")
def get_icon(icon_id: str) -> FileResponse:
    """Serve the PNG file for a given icon_id.

    The icons table stores a png_path; if it is relative, it is resolved
    relative to the configured data_dir. This endpoint returns 404 if the
    icon or the file does not exist.
    """
    config = get_config()

    with connect(config.database_path) as conn:
        cursor = conn.execute(
            "SELECT png_path FROM icons WHERE icon_id = ?",
            (icon_id,),
        )
        row = cursor.fetchone()

    if not row or not row["png_path"]:
        raise HTTPException(status_code=404, detail="Icon not found")

    path = Path(row["png_path"])
    if not path.is_absolute():
        # Resolve relative paths under the configured data directory
        path = Path(config.data_dir) / path

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Icon file not found")

    return FileResponse(path, media_type="image/png")
