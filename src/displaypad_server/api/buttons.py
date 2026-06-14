from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_buttons() -> dict[str, str]:
    return {"status": "placeholder", "module": "buttons"}
