"""Usage logging + spend cap. Every model call goes through record_call (AGENTS.md §3 Cost)."""

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select

from app.config import settings
from app.core.models import token_cost
from app.db import SessionLocal
from app.tables import ModelCall

KST = timezone(timedelta(hours=9))  # no DST; avoids tzdata in slim images
USAGE_LOG = Path(__file__).resolve().parents[3] / "logs" / "usage.jsonl"


class SpendCapExceeded(RuntimeError):
    pass


async def spend_summary() -> dict[str, float]:
    """Spend today (KST day) and in total, plus the caps."""
    start_of_day = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
    async with SessionLocal() as s:
        total = await s.scalar(select(func.coalesce(func.sum(ModelCall.cost_usd), 0)))
        today = await s.scalar(select(func.coalesce(func.sum(ModelCall.cost_usd), 0))
                               .where(ModelCall.created_at >= start_of_day))
    return {"today_usd": float(today), "total_usd": float(total),
            "daily_cap_usd": settings.spend_cap_usd_daily, "total_cap_usd": settings.spend_cap_usd_total}


async def check_spend_cap() -> None:
    """Call before every model call; raises SpendCapExceeded once a cap is reached."""
    # ponytail: check-then-record race, parallel workers can overshoot by one call each; fine at our caps
    s = await spend_summary()
    if s["today_usd"] >= s["daily_cap_usd"]:
        raise SpendCapExceeded(f"daily cap ${s['daily_cap_usd']} reached (${s['today_usd']:.2f} today)")
    if s["total_usd"] >= s["total_cap_usd"]:
        raise SpendCapExceeded(f"total cap ${s['total_cap_usd']} reached (${s['total_usd']:.2f})")


async def record_call(request_id: str, model: str, kind: str, latency_ms: int, *,
                      usage: dict | None = None, cost_usd: float | None = None,
                      turn: int | None = None, status: str = "ok", meta: dict | None = None) -> ModelCall:
    """Persist one call (DB row = trace event) and append it to logs/usage.jsonl.

    Token models pass `usage` (Responses API shape) and cost is computed; flat-priced
    specialists (SAM, Voice, Image) pass `cost_usd`.
    """
    usage = usage or {}
    cost = token_cost(model, usage) if cost_usd is None else cost_usd
    row = ModelCall(
        request_id=request_id, model=model, kind=kind, turn=turn, status=status,
        input_tokens=usage.get("input_tokens"),
        cached_tokens=(usage.get("input_tokens_details") or {}).get("cached_tokens"),
        output_tokens=usage.get("output_tokens"),
        reasoning_tokens=(usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
        cost_usd=Decimal(str(round(cost, 6))), latency_ms=latency_ms, meta=meta or {})
    async with SessionLocal() as s:
        s.add(row)
        await s.commit()
        await s.refresh(row)  # load server-side created_at
    try:  # no logs/ volume in containers; the DB row is the source of truth
        USAGE_LOG.parent.mkdir(exist_ok=True)
        with USAGE_LOG.open("a") as f:
            f.write(json.dumps({"ts": time.time(), **trace_event(row)}) + "\n")
    except OSError:
        pass
    return row


def trace_event(row: ModelCall) -> dict:
    return {"id": row.id, "request_id": row.request_id, "model": row.model, "kind": row.kind,
            "turn": row.turn, "status": row.status, "input_tokens": row.input_tokens,
            "cached_tokens": row.cached_tokens, "output_tokens": row.output_tokens,
            "reasoning_tokens": row.reasoning_tokens, "cost_usd": float(row.cost_usd),
            "latency_ms": row.latency_ms, "meta": row.meta,
            "created_at": row.created_at.isoformat() if row.created_at else None}
