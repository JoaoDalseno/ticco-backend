import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FazendaBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str = Field(..., min_length=2, max_length=200)
    dono_nome: str = Field(..., min_length=2, max_length=200)
    dono_wpp: str | None = Field(None, pattern=r"^\+55\d{10,11}$")
    cidade: str = Field(..., max_length=100)
    estado: str = Field(..., min_length=2, max_length=2, description="Sigla UF")
    area_total_ha: float = Field(..., gt=0)
    latitude: float | None = None
    longitude: float | None = None
    modulo_dono_ativo: bool = False


class FazendaCreate(FazendaBase):
    """`agronomo_id` é resolvido a partir do JWT — não vem no body."""
    pass


class FazendaUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    dono_nome: str | None = None
    dono_wpp: str | None = None
    modulo_dono_ativo: bool | None = None
    latitude: float | None = None
    longitude: float | None = None


class FazendaRead(FazendaBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agronomo_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
