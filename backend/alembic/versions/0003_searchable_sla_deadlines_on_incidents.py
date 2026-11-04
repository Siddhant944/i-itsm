"""Store the SLA deadlines and the at-risk moment on ``incidents`` (D-018).

All three are derived from the incident's SLA clock and kept by the mapper. Storing them lets a
search filter by SLA status with plain comparisons, which both SQLite and PostgreSQL index,
instead of the datetime arithmetic the two dialects spell differently.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-04 10:42:27.371364+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.repositories.sqlalchemy import types as itsm

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sla_response_deadline", itsm.UtcDateTime(), nullable=True))
        batch_op.add_column(sa.Column("sla_resolution_deadline", itsm.UtcDateTime(), nullable=True))
        batch_op.add_column(sa.Column("sla_resolution_risk_at", itsm.UtcDateTime(), nullable=True))
        batch_op.create_index(
            "ix_incidents_status_sla_resolution_deadline",
            ["status", "sla_resolution_deadline"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("incidents", schema=None) as batch_op:
        batch_op.drop_index("ix_incidents_status_sla_resolution_deadline")
        batch_op.drop_column("sla_resolution_risk_at")
        batch_op.drop_column("sla_resolution_deadline")
        batch_op.drop_column("sla_response_deadline")
