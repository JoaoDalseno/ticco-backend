import enum
import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class StatusVisitaEnum(str, enum.Enum):
    pendente = "pendente"
    processando = "processando"
    completa = "completa"
    erro = "erro"


class Visita(Base, TimestampMixin):
    __tablename__ = "visitas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agronomo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agronomos.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    fazenda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fazendas.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    talhao_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("talhoes.id", ondelete="SET NULL"),
        nullable=True,
    )
    mensagem_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("mensagens.id", ondelete="SET NULL"),
        nullable=True,
    )
    data_visita: Mapped[date] = mapped_column(Date, nullable=False)
    texto_bruto: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON estruturado pelo Claude — schema em schemas/visita.py
    dados_estruturados: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Embedding pgvector 1536 dims (text-embedding-3-small)
    # Definido como coluna genérica para evitar dep em tempo de import
    pdf_relatorio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_receituario_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    enviado_para_dono: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[StatusVisitaEnum] = mapped_column(
        Enum(StatusVisitaEnum, name="status_visita_enum"),
        nullable=False,
        default=StatusVisitaEnum.pendente,
    )
    erro_descricao: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relacionamentos
    agronomo: Mapped["Agronomo"] = relationship(  # type: ignore[name-defined]
        "Agronomo", back_populates="visitas"
    )
    fazenda: Mapped["Fazenda"] = relationship(  # type: ignore[name-defined]
        "Fazenda", back_populates="visitas"
    )
    talhao: Mapped["Talhao | None"] = relationship(  # type: ignore[name-defined]
        "Talhao", back_populates="visitas"
    )
    mensagem: Mapped["Mensagem | None"] = relationship(  # type: ignore[name-defined]
        "Mensagem", back_populates="visita"
    )
    receituario: Mapped["Receituario | None"] = relationship(  # type: ignore[name-defined]
        "Receituario", back_populates="visita", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Visita {self.data_visita} — status: {self.status}>"
