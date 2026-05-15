import uuid

from sqlalchemy import Boolean, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Fazenda(Base, TimestampMixin):
    __tablename__ = "fazendas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    agronomo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agronomos.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nome: Mapped[str] = mapped_column(String(200), nullable=False)
    dono_nome: Mapped[str] = mapped_column(String(200), nullable=False)
    dono_wpp: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cidade: Mapped[str] = mapped_column(String(100), nullable=False)
    # Sigla do estado: SP, MG, GO...
    estado: Mapped[str] = mapped_column(String(2), nullable=False)
    area_total_ha: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Ativa acesso do módulo Dono (Ticco Completo)
    modulo_dono_ativo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relacionamentos
    agronomo: Mapped["Agronomo"] = relationship(  # type: ignore[name-defined]
        "Agronomo", back_populates="fazendas"
    )
    talhoes: Mapped[list["Talhao"]] = relationship(  # type: ignore[name-defined]
        "Talhao", back_populates="fazenda", cascade="all, delete-orphan"
    )
    visitas: Mapped[list["Visita"]] = relationship(  # type: ignore[name-defined]
        "Visita", back_populates="fazenda"
    )

    def __repr__(self) -> str:
        return f"<Fazenda {self.nome} — {self.cidade}/{self.estado}>"
