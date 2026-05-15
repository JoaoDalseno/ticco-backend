import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class StatusReceituarioEnum(str, enum.Enum):
    rascunho = "rascunho"
    assinado = "assinado"
    enviado = "enviado"


class Receituario(Base, TimestampMixin):
    __tablename__ = "receituarios"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    visita_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("visitas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Número de série único: TICCO-2026-000001
    numero_serie: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    # Lista de produtos: [{nome, principio_ativo, dose, ...}]
    produtos: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    hash_assinatura: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pdf_assinado_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enviado_para_revenda: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[StatusReceituarioEnum] = mapped_column(
        Enum(StatusReceituarioEnum, name="status_receituario_enum"),
        nullable=False,
        default=StatusReceituarioEnum.rascunho,
    )

    # Relacionamentos
    visita: Mapped["Visita"] = relationship(  # type: ignore[name-defined]
        "Visita", back_populates="receituario"
    )

    def __repr__(self) -> str:
        return f"<Receituario {self.numero_serie} — {self.status}>"
