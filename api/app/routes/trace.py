import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.core.spend import spend_summary, trace_event
from app.db import SessionLocal
from app.tables import ModelCall

router = APIRouter()


@router.get("/trace/{request_id}")
async def trace(request_id: str, request: Request) -> StreamingResponse:
    """SSE stream of model calls for one request: replays past rows, then follows new ones."""

    async def events():
        last_id, idle = 0, 0.0
        yield ": connected\n\n"  # Cloudflare holds headers until the first body byte
        while not await request.is_disconnected():
            # ponytail: 0.5 s DB poll, switch to LISTEN/NOTIFY if trace latency ever matters
            async with SessionLocal() as s:
                rows = (await s.scalars(select(ModelCall)
                        .where(ModelCall.request_id == request_id, ModelCall.id > last_id)
                        .order_by(ModelCall.id))).all()
            for row in rows:
                last_id = row.id
                yield f"id: {row.id}\nevent: model_call\ndata: {json.dumps(trace_event(row))}\n\n"
            idle = 0.0 if rows else idle + 0.5
            if idle >= 15:  # keep nginx / Cloudflare from closing an idle stream
                idle = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/spend")
async def spend() -> dict[str, float]:
    return await spend_summary()
