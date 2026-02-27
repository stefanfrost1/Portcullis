from fastapi import APIRouter, HTTPException
from docker.errors import NotFound, APIError

from src.models.schemas import APIResponse
from src.services import docker_service as ds

router = APIRouter(prefix="/networks", tags=["Networks"])


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
