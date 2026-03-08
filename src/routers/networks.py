from fastapi import APIRouter, Depends, HTTPException, status
from docker.errors import NotFound, APIError

from src.models.schemas import APIResponse, NetworkCreateRequest
from src.routers._auth import require_admin
from src.services import docker_service as ds

router = APIRouter(prefix="/networks", tags=["Networks"], dependencies=[Depends(require_admin)])


@router.get("", summary="List networks", response_model=APIResponse)
def list_networks():
    try:
        return APIResponse(data=ds.list_networks())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{network_id}", summary="Inspect network", response_model=APIResponse)
def get_network(network_id: str):
    try:
        return APIResponse(data=ds.get_network(network_id))
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Network '{network_id}' not found")
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("", summary="Create network", response_model=APIResponse, status_code=status.HTTP_201_CREATED)
def create_network(body: NetworkCreateRequest):
    try:
        return APIResponse(data=ds.create_network(body.name, body.driver, body.internal, body.labels))
    except APIError as exc:
        if "already exists" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"Network '{body.name}' already exists")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{network_id}", summary="Remove network", response_model=APIResponse)
def remove_network(network_id: str):
    try:
        ds.remove_network(network_id)
        return APIResponse(data={"removed": network_id})
    except NotFound:
        raise HTTPException(status_code=404, detail=f"Network '{network_id}' not found")
    except APIError as exc:
        if "active endpoints" in str(exc).lower():
            raise HTTPException(status_code=409, detail="Network has active endpoints and cannot be removed")
        raise HTTPException(status_code=500, detail=str(exc))
