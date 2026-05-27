"""add_clicksign_keys_to_receituario

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "receituarios",
        sa.Column("clicksign_envelope_key", sa.String(255), nullable=True),
    )
    op.add_column(
        "receituarios",
        sa.Column("clicksign_signer_key", sa.String(255), nullable=True),
    )
    # Índice para lookup rápido no webhook (buscamos por envelope_key)
    op.create_index(
        "ix_receituarios_clicksign_envelope_key",
        "receituarios",
        ["clicksign_envelope_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_receituarios_clicksign_envelope_key", table_name="receituarios")
    op.drop_column("receituarios", "clicksign_signer_key")
    op.drop_column("receituarios", "clicksign_envelope_key")
