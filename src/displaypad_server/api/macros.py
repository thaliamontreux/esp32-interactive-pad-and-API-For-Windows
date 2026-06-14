from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_macros() -> dict[str, str]:
    return {"status": "placeholder", "module": "macros"}
