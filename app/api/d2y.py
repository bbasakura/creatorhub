from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..services.d2y import default_batch_size, enqueue_d2y, import_batch

router = APIRouter(prefix='/api/youtube/d2y', tags=['d2y'])


class D2YImportIn(BaseModel):
    batch_size: int | None = Field(default=None, ge=1, le=100)
    visibility: str = 'public'
    interval_seconds: int = Field(default=150, ge=0, le=86400)
    account_id: int | None = None
    start_time: datetime | None = None
    request_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,100}$')


@router.get('/defaults')
def defaults():
    return {'batch_size': default_batch_size(), 'interval_seconds': 150}


@router.post('/import-batch')
async def import_d2y_batch(body: D2YImportIn = D2YImportIn()):
    try:
        return await run_in_threadpool(import_batch, **body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


class D2YEnqueueIn(BaseModel):
    manifest_version: int = Field(default=1, ge=1, le=1)
    account_id: int | None = None
    videos: list[dict] = Field(max_length=100)
    visibility: str = 'public'
    interval_seconds: int = Field(default=150, ge=0, le=86400)
    start_time: datetime | None = None
    intent_id: str = Field(default='initial', pattern=r'^[A-Za-z0-9_-]{1,80}$')


@router.post('/enqueue')
async def enqueue(body: D2YEnqueueIn):
    try:
        return await run_in_threadpool(enqueue_d2y, **body.model_dump())
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from exc
