import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, Numeric, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (
        Index("ix_executions_workspace_created_at", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    workflow_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True, index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    agent_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # The API key that made this call, when the trigger was the public /v1
    # surface — the per-key spend ledger sums this column.
    api_key_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # pending, running, completed, failed, cancelled
    trigger_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # manual, api, scheduled, webhook, chat
    input_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    execution_trace: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    execution_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    # Snapshot of the model that served this run. The agent's LLM profile can be
    # edited later, so the live profile is not a reliable record of the past.
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Milliseconds from run start to the first streamed chunk. LangChain does not
    # report this, so the runtime measures it.
    ttft_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workflow = relationship("Workflow", back_populates="executions")
