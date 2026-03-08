from fastapi import APIRouter, Depends, HTTPException, Query, status
from docker.errors import NotFound, ImageNotFound, APIError, BuildError

from src.models.schemas import APIResponse, ImagePullRequest
from src.routers._auth import require_admin
from src.services import docker_service as ds

router = APIRouter(prefix="/images", tags=["Images"], dependencies=[Depends(require_admin)])


@router.get("", summary="List images", response_model=APIResponse)
def list_images(all_images: bool = Query(False, description="Include intermediate layers")):
    try:
        return APIResponse(data=ds.list_images(all_images=all_images))
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/{image_id:path}", summary="Inspect image", response_model=APIResponse)
def get_image(image_id: str):
    try:
        return APIResponse(data=ds.get_image(image_id))
    except (NotFound, ImageNotFound):
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' not found")
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{image_id:path}", summary="Remove image", response_model=APIResponse)
def remove_image(
    image_id: str,
    force: bool = Query(False),
    no_prune: bool = Query(False, description="Do not delete untagged parent layers"),
):
    try:
        ds.remove_image(image_id, force=force, no_prune=no_prune)
        return APIResponse(data={"removed": image_id})
    except (NotFound, ImageNotFound):
        raise HTTPException(status_code=404, detail=f"Image '{image_id}' not found")
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pull", summary="Pull an image from a registry", response_model=APIResponse)
def pull_image(body: ImagePullRequest):
    try:
        return APIResponse(data=ds.pull_image(body.repository, tag=body.tag))
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/prune", summary="Remove unused (dangling) images", response_model=APIResponse)
def prune_images():
    try:
        return APIResponse(data=ds.prune_images())
    except APIError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
