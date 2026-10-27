from datetime import datetime, timedelta, timezone

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import delete

from app.config import settings
from app.db import SessionLocal
from app.tables import Document

DOCUMENT_RETENTION = timedelta(days=7)  # docs/03 §5: uploaded images deleted after 7 days


async def ping(ctx: dict) -> str:
    return "pong"


async def purge_documents(ctx: dict | None = None) -> int:
    """Delete redacted documents older than the retention window; returns how many."""
    cutoff = datetime.now(timezone.utc) - DOCUMENT_RETENTION
    async with SessionLocal() as s:
        result = await s.execute(delete(Document).where(Document.created_at < cutoff))
        await s.commit()
    return result.rowcount


class WorkerSettings:
    functions = [ping]
    cron_jobs = [cron(purge_documents, minute=0, run_at_startup=True)]  # hourly
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
