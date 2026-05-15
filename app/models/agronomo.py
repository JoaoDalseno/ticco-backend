import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class PlanoEnum(str, enum.Enum):
    free = "free"
    basico = "basico"
    completo = "completo"


class StatusPagamentoEnum(str, enum.Enum):
    trial = "trial"
    active = "active"
    past_due = "past_due"
    canceled = "canceled"


class Agronomo(Base, TimestampMixin):
    __tablename__ = "agronomos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    cpf: Mapped[str] = mapped_column(String(14), unique=True, nullable=False)
    crea: Mapped[str] = mapped_column(String(50), nullable=False)
    # Formato E.164: +5516999998888
    telefone_wpp: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    certificado_icp_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    plano: Mapped[PlanoEnum] = mapped_column(
        Enum(PlanoEnum, name="plano_enum"), nullable=False, default=PlanoEnum.free
    )
    status_pagamento: Mapped[StatusPagamentoEnum] = mapped_column(
        Enum(StatusPagamentoEnum, name="status_pagamento_enum"),
        nullable=False,
        default=StatusPagamentoEnum.trial,
    )
    trial_ate: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Relacionamentos
    fazendas: Mapped[list["Fazenda"]] = relationship(  # type: ignore[name-defined]
        "Fazenda", back_populates="agronomo", cascade="all, delete-orphan"
    )
    mensagens: Mapped[list["Mensagem"]] = relationship(  # type: ignore[name-defined]
        "Mensagem", back_populates="agronomo"
    )
    visitas: Mapped[list["Visita"]] = relationship(  # type: ignore[name-defined]
        "Visita", back_populates="agronomo"
    )

    def __repr__(self) -> str:
        return f"<Agronomo {self.nome} — CREA {self.crea}>"
