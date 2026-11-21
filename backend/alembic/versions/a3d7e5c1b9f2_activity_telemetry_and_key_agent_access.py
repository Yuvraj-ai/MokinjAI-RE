"""activity telemetry and API key agent access

Executions gain a model snapshot (provider, model_id) and time to first token, so
the Activity dashboard reports the model that actually served a run even after the
agent's LLM profile is edited. A composite index serves the dashboard's
workspace + date-range queries.

API keys gain `all_agents` (default true, so every existing key keeps working
exactly as before) and the `api_key_agents` join table for keys limited to a set
of agents.

Revision ID: a3d7e5c1b9f2
Revises: 9a1c2e3f4b5c
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3d7e5c1b9f2"
down_revision: Union[str, None] = "9a1c2e3f4b5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("executions", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("executions", sa.Column("model_id", sa.String(255), nullable=True))
    op.add_column("executions", sa.Column("ttft_ms", sa.Integer(), nullable=True))
    op.create_index(
        "ix_executions_workspace_created_at",
        "executions",
        ["workspace_id", "created_at"],
    )

    op.add_column(
        "api_keys",
        sa.Column(
            "all_agents", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    op.create_table(
        "api_key_agents",
        sa.Column(
            "api_key_id",
            sa.String(36),
            sa.ForeignKey("api_keys.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_api_key_agents_agent_id", "api_key_agents", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_api_key_agents_agent_id", table_name="api_key_agents")
    op.drop_table("api_key_agents")
    op.drop_column("api_keys", "all_agents")
    op.drop_index("ix_executions_workspace_created_at", table_name="executions")
    op.drop_column("executions", "ttft_ms")
    op.drop_column("executions", "model_id")
    op.drop_column("executions", "provider")
