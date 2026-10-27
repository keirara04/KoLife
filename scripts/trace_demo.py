"""Mock trace emitter + self-check for record_call / spend cap. No live model calls.

    cd api && DATABASE_URL=postgresql+asyncpg://localhost/kolife uv run python ../scripts/trace_demo.py [--keep]

Records a fake orchestrator request (Wonder turn -> 2 parallel Spark workers + SAM -> Wonder final)
under one request_id, 1 s apart, so `curl -N localhost:8000/api/trace/<id>` shows them live.
Asserts the cap trips, then deletes the rows unless --keep (mock rows would count toward spend).
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from sqlalchemy import delete  # noqa: E402

from app.config import settings  # noqa: E402
from app.core import models as m  # noqa: E402
from app.core.spend import SpendCapExceeded, check_spend_cap, record_call, spend_summary  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.tables import ModelCall  # noqa: E402


def usage(inp: int, cached: int, out: int, reasoning: int) -> dict:
    return {"input_tokens": inp, "output_tokens": out, "input_tokens_details": {"cached_tokens": cached},
            "output_tokens_details": {"reasoning_tokens": reasoning}}


async def main() -> None:
    rid = uuid.uuid4().hex[:12]
    print(f"request_id={rid}  ->  curl -N localhost:8000/api/trace/{rid}")
    await asyncio.sleep(3)  # time to start curl
    steps = [
        dict(model=m.WONDER, kind="orchestrator", turn=0, latency_ms=4700, usage=usage(578, 0, 390, 225)),
        dict(model=m.SPARK, kind="worker", turn=0, latency_ms=3200, usage=usage(2100, 1800, 640, 300)),
        dict(model=m.SPARK, kind="worker", turn=0, latency_ms=2900, usage=usage(1900, 1800, 520, 250)),
        dict(model=m.SAM, kind="sam", turn=0, latency_ms=4600, cost_usd=m.SAM_PER_IMAGE,
             meta={"concept": "registration number", "detections": 1}),
        dict(model=m.WONDER, kind="orchestrator", turn=1, latency_ms=6700, usage=usage(1050, 512, 600, 508)),
    ]
    rows = []
    for step in steps:
        await check_spend_cap()
        row = await record_call(rid, meta={"mock": True, **step.pop("meta", {})}, **step)
        rows.append(row)
        print(f"  #{row.id} {row.model:<18} turn={row.turn} ${float(row.cost_usd):.5f}")
        await asyncio.sleep(1)

    expected = m.token_cost(m.WONDER, steps[0]["usage"])
    assert abs(float(rows[0].cost_usd) - expected) < 1e-6, (rows[0].cost_usd, expected)
    assert rows[1].cached_tokens == 1800 and rows[3].input_tokens is None
    assert rows[0].created_at is not None

    today = (await spend_summary())["today_usd"]
    mock_total = sum(float(r.cost_usd) for r in rows)
    assert today >= mock_total - 1e-6, (today, mock_total)  # KST-day sum includes our rows

    settings.spend_cap_usd_daily = 0  # any spend today now exceeds the cap
    try:
        await check_spend_cap()
        raise AssertionError("spend cap did not trip")
    except SpendCapExceeded as e:
        print(f"cap trips OK: {e}")

    if "--keep" not in sys.argv:
        async with SessionLocal() as s:
            await s.execute(delete(ModelCall).where(ModelCall.request_id == rid))
            await s.commit()
        print("mock rows deleted (use --keep for UI work)")
    print("all checks passed")


if __name__ == "__main__":
    asyncio.run(main())
