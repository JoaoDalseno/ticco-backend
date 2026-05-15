import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Talhao(Base, TimestampMixin):
    __tablename__ = "talhoes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fazenda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fazendas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nome: Mapped[str] = mapped_column(String(100), nullable=False)
    area_ha: Mapped[float] = mapped_column(Float, nullable=False)
    variedade: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ano_plantio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    espacamento: Mapped[str | None] = mapped_column(String(50), nullable=True)
    altitude: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # GeoJSON do polígono do talhão
    poligono: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relacionamentos
    fazenda: Mapped["Fazenda"] = relationship(  # type: ignore[name-defined]
        "Fazenda", back_populates="talhoes"
    )
    visitas: Mapped[list["Visita"]] = relationship(  # type: ignore[name-defined]
        "Visita", back_populates="talhao"
    )

    def __repr__(self) -> str:
        return f"<Talhao {self.nome} — {self.area_ha}ha>"
