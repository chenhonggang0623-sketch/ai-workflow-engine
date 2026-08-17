import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.blueprint import Blueprint
from app.agent.llm_gateway import LLMGateway
from app.planner.architect import Architect
from app.schemas.blueprint import (
    BlueprintListResponse,
    BlueprintResponse,
    BlueprintReviseRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{workflow_id}", response_model=BlueprintResponse)
async def get_latest_blueprint(workflow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Blueprint)
        .where(Blueprint.workflow_id == workflow_id, Blueprint.status == "active")
        .order_by(Blueprint.version.desc())
        .limit(1)
    )
    blueprint = result.scalar_one_or_none()
    if not blueprint:
        raise HTTPException(404, "No blueprint found for this workflow")
    return blueprint


@router.get("/{workflow_id}/versions", response_model=BlueprintListResponse)
async def list_blueprint_versions(workflow_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Blueprint)
        .where(Blueprint.workflow_id == workflow_id)
        .order_by(Blueprint.version)
    )
    versions = result.scalars().all()
    if not versions:
        raise HTTPException(404, "No blueprint found for this workflow")
    return BlueprintListResponse(workflow_id=workflow_id, versions=versions)


@router.post("/{blueprint_id}/revise", response_model=BlueprintResponse)
async def revise_blueprint(
    blueprint_id: UUID,
    body: BlueprintReviseRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    blueprint = await db.get(Blueprint, blueprint_id)
    if not blueprint:
        raise HTTPException(404, "Blueprint not found")

    llm: LLMGateway = request.app.state.llm_gateway
    architect = Architect(llm)
    try:
        revised = await architect.revise(blueprint.content, body.feedback)
        saved = await architect.save(
            revised,
            db,
            workflow_id=blueprint.workflow_id,
            source_execution_id=blueprint.source_execution_id,
        )
        await db.commit()
        return saved
    except Exception as e:
        logger.exception("Blueprint revision failed: %s", e)
        raise HTTPException(500, f"Blueprint revision failed: {e}")
