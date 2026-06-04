"""increase_mensagens_column_lengths

Aumenta o limite de colunas VARCHAR da tabela `mensagens` para suportar
identificadores e URLs maiores da Evolution API:

  - telefone_origem:  VARCHAR(20)  → VARCHAR(50)
      Cobre jids longos eventuais (sem grupos, que são filtrados antes).
  - midia_url:        VARCHAR(500) → VARCHAR(2000)
      Signed URLs da Evolution API podem ultrapassar 500 chars.
  - zapi_message_id:  VARCHAR(100) → VARCHAR(200)
      Formatos de message_id da Evolution são mais longos que Z-API.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "mensagens",
        "telefone_origem",
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=False,
    )
    op.alter_column(
        "mensagens",
        "midia_url",
        existing_type=sa.String(500),
        type_=sa.String(2000),
        existing_nullable=True,
    )
    op.alter_column(
        "mensagens",
        "zapi_message_id",
        existing_type=sa.String(100),
        type_=sa.String(200),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "mensagens",
        "zapi_message_id",
        existing_type=sa.String(200),
        type_=sa.String(100),
        existing_nullable=True,
    )
    op.alter_column(
        "mensagens",
        "midia_url",
        existing_type=sa.String(2000),
        type_=sa.String(500),
        existing_nullable=True,
    )
    op.alter_column(
        "mensagens",
        "telefone_origem",
        existing_type=sa.String(50),
        type_=sa.String(20),
        existing_nullable=False,
    )
