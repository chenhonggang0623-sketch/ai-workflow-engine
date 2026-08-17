from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.contract.contract_manager import ContractManager
from app.schemas.contract import ContractCreate, ContractResponse

router = APIRouter()


class CompleteRequest(BaseModel):
    result: dict


class FailRequest(BaseModel):
    error: str


class DisputeRequest(BaseModel):
    reason: str


@router.get("", response_model=list[ContractResponse])
async def list_contracts(
    executor_id: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    mgr = ContractManager(db)
    contracts = await mgr.list(executor_id=executor_id, status=status)
    return contracts


@router.get("/{id}", response_model=ContractResponse)
async def get_contract(id: UUID, db: AsyncSession = Depends(get_db)):
    mgr = ContractManager(db)
    contract = await mgr.get(id)
    if not contract:
        raise HTTPException(404, "Contract not found")
    return contract


@router.post("/{id}/accept", response_model=ContractResponse)
async def accept_contract(id: UUID, db: AsyncSession = Depends(get_db)):
    mgr = ContractManager(db)
    try:
        contract = await mgr.accept(id)
        return contract
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{id}/complete", response_model=ContractResponse)
async def complete_contract(id: UUID, body: CompleteRequest, db: AsyncSession = Depends(get_db)):
    mgr = ContractManager(db)
    try:
        contract = await mgr.complete(id, body.result)
        return contract
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{id}/fail", response_model=ContractResponse)
async def fail_contract(id: UUID, body: FailRequest, db: AsyncSession = Depends(get_db)):
    mgr = ContractManager(db)
    try:
        contract = await mgr.fail(id, body.error)
        return contract
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/{id}/dispute", response_model=ContractResponse)
async def dispute_contract(id: UUID, body: DisputeRequest, db: AsyncSession = Depends(get_db)):
    mgr = ContractManager(db)
    try:
        contract = await mgr.dispute(id, body.reason)
        return contract
    except ValueError as e:
        raise HTTPException(400, str(e))
