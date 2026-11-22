"""chat message output format

Assistant replies record how they were generated ("markdown" or "openui") so a
replayed session renders each reply the way it was produced. The column is
nullable with no backfill: rows from before this feature read as Markdown, and
code that predates the column ignores it.

Rollback drops the column; only the format labels are lost, never reply text.

Revision ID: b4e8f6d2c0a3
Revises: a3d7e5c1b9f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8f6d2c0a3"
down_revision: Union[str, None] = "a3d7e5c1b9f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("chat_messages", sa.Column("output_format", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_messages", "output_format")
