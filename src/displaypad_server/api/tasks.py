from fastapi import APIRouter

router = APIRouter()


@router.get("/")
def list_tasks() -> dict[str, str]:
    return {"status": "placeholder", "module": "tasks"}
