"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-14
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Habilita extensão pgvector (já ativa no Supabase, mas idempotente)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Agronomos ────────────────────────────────────────────────────────────
    op.create_table(
        "agronomos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("cpf", sa.String(14), nullable=False),
        sa.Column("crea", sa.String(50), nullable=False),
        sa.Column("telefone_wpp", sa.String(20), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("certificado_icp_url", sa.String(500), nullable=True),
        sa.Column(
            "plano",
            sa.Enum("free", "basico", "completo", name="plano_enum"),
            nullable=False,
            server_default="free",
        ),
        sa.Column(
            "status_pagamento",
            sa.Enum("trial", "active", "past_due", "canceled", name="status_pagamento_enum"),
            nullable=False,
            server_default="trial",
        ),
        sa.Column("trial_ate", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stripe_customer_id", sa.String(100), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("cpf", name="uq_agronomos_cpf"),
        sa.UniqueConstraint("telefone_wpp", name="uq_agronomos_telefone_wpp"),
    )

    # ── Fazendas ─────────────────────────────────────────────────────────────
    op.create_table(
        "fazendas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agronomo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(200), nullable=False),
        sa.Column("dono_nome", sa.String(200), nullable=False),
        sa.Column("dono_wpp", sa.String(20), nullable=True),
        sa.Column("cidade", sa.String(100), nullable=False),
        sa.Column("estado", sa.String(2), nullable=False),
        sa.Column("area_total_ha", sa.Float, nullable=False),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("modulo_dono_ativo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agronomo_id"], ["agronomos.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_fazendas_agronomo_id", "fazendas", ["agronomo_id"])

    # ── Talhoes ──────────────────────────────────────────────────────────────
    op.create_table(
        "talhoes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("fazenda_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nome", sa.String(100), nullable=False),
        sa.Column("area_ha", sa.Float, nullable=False),
        sa.Column("variedade", sa.String(100), nullable=True),
        sa.Column("ano_plantio", sa.Integer, nullable=True),
        sa.Column("espacamento", sa.String(50), nullable=True),
        sa.Column("altitude", sa.Integer, nullable=True),
        sa.Column("poligono", sa.JSON, nullable=True),
        sa.Column("ativo", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["fazenda_id"], ["fazendas.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_talhoes_fazenda_id", "talhoes", ["fazenda_id"])

    # ── Mensagens ────────────────────────────────────────────────────────────
    op.create_table(
        "mensagens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agronomo_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("telefone_origem", sa.String(20), nullable=False),
        sa.Column(
            "direcao",
            sa.Enum("recebida", "enviada", name="direcao_enum"),
            nullable=False,
        ),
        sa.Column(
            "tipo",
            sa.Enum("texto", "audio", "imagem", "documento", name="tipo_enum"),
            nullable=False,
        ),
        sa.Column("conteudo_texto", sa.Text, nullable=True),
        sa.Column("midia_url", sa.String(500), nullable=True),
        sa.Column("transcricao", sa.Text, nullable=True),
        sa.Column("processada", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("zapi_message_id", sa.String(100), nullable=True),
        sa.Column("raw_payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agronomo_id"], ["agronomos.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_mensagens_agronomo_id", "mensagens", ["agronomo_id"])
    op.create_index("ix_mensagens_telefone_origem", "mensagens", ["telefone_origem"])
    op.create_index("ix_mensagens_zapi_message_id", "mensagens", ["zapi_message_id"])

    # ── Visitas ──────────────────────────────────────────────────────────────
    op.create_table(
        "visitas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("agronomo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fazenda_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("talhao_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mensagem_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data_visita", sa.Date, nullable=False),
        sa.Column("texto_bruto", sa.Text, nullable=False),
        sa.Column("dados_estruturados", sa.JSON, nullable=False, server_default="{}"),
        # Coluna vector(1536) para embeddings pgvector
        sa.Column("embedding", sa.Text, nullable=True),  # substituído abaixo via SQL
        sa.Column("pdf_relatorio_url", sa.String(500), nullable=True),
        sa.Column("pdf_receituario_url", sa.String(500), nullable=True),
        sa.Column("enviado_para_dono", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "status",
            sa.Enum("pendente", "processando", "completa", "erro", name="status_visita_enum"),
            nullable=False,
            server_default="pendente",
        ),
        sa.Column("erro_descricao", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["agronomo_id"], ["agronomos.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fazenda_id"], ["fazendas.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["talhao_id"], ["talhoes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["mensagem_id"], ["mensagens.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_visitas_agronomo_id", "visitas", ["agronomo_id"])
    op.create_index("ix_visitas_fazenda_id", "visitas", ["fazenda_id"])

    # Substitui coluna text por vector(1536) real
    op.execute("ALTER TABLE visitas DROP COLUMN embedding")
    op.execute("ALTER TABLE visitas ADD COLUMN embedding vector(1536)")

    # ── Receituarios ─────────────────────────────────────────────────────────
    op.create_table(
        "receituarios",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("visita_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numero_serie", sa.String(30), nullable=False),
        sa.Column("produtos", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("hash_assinatura", sa.String(200), nullable=True),
        sa.Column("pdf_assinado_url", sa.String(500), nullable=True),
        sa.Column("enviado_para_revenda", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "status",
            sa.Enum("rascunho", "assinado", "enviado", name="status_receituario_enum"),
            nullable=False,
            server_default="rascunho",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["visita_id"], ["visitas.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("numero_serie", name="uq_receituarios_numero_serie"),
    )
    op.create_index("ix_receituarios_visita_id", "receituarios", ["visita_id"])


def downgrade() -> None:
    op.drop_table("receituarios")
    op.drop_table("visitas")
    op.drop_table("mensagens")
    op.drop_table("talhoes")
    op.drop_table("fazendas")
    op.drop_table("agronomos")

    op.execute("DROP TYPE IF EXISTS status_receituario_enum")
    op.execute("DROP TYPE IF EXISTS status_visita_enum")
    op.execute("DROP TYPE IF EXISTS tipo_enum")
    op.execute("DROP TYPE IF EXISTS direcao_enum")
    op.execute("DROP TYPE IF EXISTS status_pagamento_enum")
    op.execute("DROP TYPE IF EXISTS plano_enum")
