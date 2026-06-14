from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from displaypad_server.core.config import get_config
from displaypad_server import application_icons as app_icons_repo

router = APIRouter()


@router.get("/application-icons/{application_id}.png")
def get_application_icon(application_id: int) -> FileResponse:
    """Serve the PNG icon for a given application_id.

    This uses the application_icons table and does not touch the existing
    2-bit icon system. Content-Type is always image/png.
    """
    config = get_config()

    record = app_icons_repo.get_primary_icon_for_application(application_id)
    if record is None or not record.icon_path:
        raise HTTPException(status_code=404, detail="Application icon not found")

    path = Path(record.icon_path)
    if not path.is_absolute():
        # application_icon_importer stores icons as relative paths under a
        # top-level ./application-icons directory next to data_dir. Resolve
        # them against the project root (parent of data_dir).
        project_root = Path(config.data_dir).parent
        path = project_root / path

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Application icon file not found")

    return FileResponse(path, media_type="image/png")
