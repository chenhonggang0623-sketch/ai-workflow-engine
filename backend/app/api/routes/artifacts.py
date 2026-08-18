from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.config import settings
from app.artifact.manager import ArtifactManager
from app.schemas.artifact import ArtifactResponse

router = APIRouter()


@router.get("", response_model=list[ArtifactResponse])
async def list_artifacts(
    execution_id: UUID | None = None,
    node_id: str | None = None,
    type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    mgr = ArtifactManager(db, settings.storage_path)
    artifacts = await mgr.list_artifacts(
        execution_id=execution_id,
        node_id=node_id,
        type=type,
    )
    return artifacts


@router.get("/{id}", response_model=ArtifactResponse)
async def get_artifact(id: UUID, db: AsyncSession = Depends(get_db)):
    mgr = ArtifactManager(db, settings.storage_path)
    artifact = await mgr.get(id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    return artifact


@router.get("/{id}/download")
async def download_artifact(id: UUID, db: AsyncSession = Depends(get_db)):
    mgr = ArtifactManager(db, settings.storage_path)
    artifact = await mgr.get(id)
    if not artifact:
        raise HTTPException(404, "Artifact not found")
    content = await mgr.get_content(id)
    if content is None:
        raise HTTPException(404, "Artifact content not found")
    from fastapi.responses import Response
    media_type = artifact.mime_type or "application/octet-stream"
    return Response(content=content, media_type=media_type)


@router.post("", response_model=ArtifactResponse, status_code=201)
async def upload_artifact(
    file: UploadFile = File(...),
    execution_id: UUID = Form(...),
    node_id: str = Form(...),
    name: str | None = Form(None),
    type: str = Form("file"),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    artifact_name = name or file.filename or "unnamed"
    mgr = ArtifactManager(db, settings.storage_path)
    artifact = await mgr.store(
        execution_id=execution_id,
        node_id=node_id,
        name=artifact_name,
        content=content,
        type=type,
    )
    return artifact


@router.delete("/{id}", status_code=204)
async def delete_artifact(id: UUID, db: AsyncSession = Depends(get_db)):
    mgr = ArtifactManager(db, settings.storage_path)
    deleted = await mgr.delete(id)
    if not deleted:
        raise HTTPException(404, "Artifact not found")
