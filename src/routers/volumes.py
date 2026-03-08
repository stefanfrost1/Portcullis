from fastapi import APIRouter, Depends, HTTPException, status
from docker.errors import NotFound, APIError

from src.models.schemas import APIResponse, VolumeCreateRequest
from src.routers._auth import require_admin
from src.services import docker_service as ds

router = APIRouter(prefix="/volumes", tags=["Volumes"], dependencies=[Depends(require_admin)])


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


@router.post("", summary="Create volume", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
def create_volume(body: VolumeCreateRequest):
    try:
        return APIResponse(data=ds.create_volume(body.name, body.driver, body.labels))
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{volume_name}", summary="Remove volume", response_model=APIResponse)
def remove_volume(volume_name: str, force: bool = False):
    try:
        ds.remove_volume(volume_name, force=force)
        return APIResponse(data={"removed": volume_name})
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Volume '{volume_name}' not found")
    except APIError as exc:
        if "in use" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Volume is in use and cannot be removed")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prune", summary="Remove unused volumes", response_model=APIResponse)
def prune_volumes():
    try:
        return APIResponse(data=ds.prune_volumes())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
