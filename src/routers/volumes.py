from fastapi import APIRouter, HTTPException
from docker.errors import NotFound, APIError

from src.models.schemas import APIResponse
from src.services import docker_service as ds

router = APIRouter(prefix="/volumes", tags=["Volumes"])


@router.get("", summary="List volumes", response_model=APIResponse)
def list_volumes():
    try:
        return APIResponse(data=ds.list_volumes())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{volume_name}", summary="Inspect volume", response_model=APIResponse)
def get_volume(volume_name: str):
    try:
        return APIResponse(data=ds.get_volume(volume_name))
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Volume '{volume_name}' not found")
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prune", summary="Remove unused volumes", response_model=APIResponse)
def prune_volumes():
    try:
        return APIResponse(data=ds.prune_volumes())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
