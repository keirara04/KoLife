from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class ModelCall(Base):
    """One row per model call: feeds the trace panel and the spend cap."""

    __tablename__ = "model_calls"
    __table_args__ = (Index("ix_model_calls_request_id_id", "request_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32))  # orchestrator | worker | sam | voice | image | open
    turn: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error
    # token columns stay null for SAM / Voice / Image
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=0)
    latency_ms: Mapped[int] = mapped_column(Integer)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)  # SAM concept, audio_ms, error text...
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True)
