import enum
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class DirecaoEnum(str, enum.Enum):
    recebida = "recebida"
    enviada = "enviada"


class TipoEnum(str, enum.Enum):
    texto = "texto"
    audio = "audio"
    imagem = "imagem"
    documento = "documento"


class Mensagem(Base, TimestampMixin):
    __tablename__ = "mensagens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Pode ser None se número ainda não cadastrado (onboarding)
    agronomo_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agronomos.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Número de origem no formato E.164 (50 chars suporta jids longos eventuais)
    telefone_origem: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    direcao: Mapped[DirecaoEnum] = mapped_column(
        Enum(DirecaoEnum, name="direcao_enum"), nullable=False
    )
    tipo: Mapped[TipoEnum] = mapped_column(
        Enum(TipoEnum, name="tipo_enum"), nullable=False
    )
    conteudo_texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    # URLs assinadas da Evolution API podem ultrapassar 500 chars com tokens
    midia_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    transcricao: Mapped[str | None] = mapped_column(Text, nullable=True)
    processada: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # IDs de mensagem (Z-API / Evolution API) — 200 chars cobre formatos longos
    zapi_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    # Payload completo do webhook Z-API — para auditoria e debug
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Relacionamentos
    agronomo: Mapped["Agronomo | None"] = relationship(  # type: ignore[name-defined]
        "Agronomo", back_populates="mensagens"
    )
    visita: Mapped["Visita | None"] = relationship(  # type: ignore[name-defined]
        "Visita", back_populates="mensagem", uselist=False
    )

    def __repr__(self) -> str:
        return f"<Mensagem {self.tipo} de {self.telefone_origem}>"
