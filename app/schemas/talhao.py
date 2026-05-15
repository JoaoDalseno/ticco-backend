import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TalhaoBase(BaseModel):
    nome: str = Field(..., min_length=1, max_length=100)
    area_ha: float = Field(..., gt=0)
    variedade: str | None = None
    ano_plantio: int | None = Field(None, ge=1900, le=2100)
    espacamento: str | None = None
    altitude: int | None = Field(None, ge=0, le=3000)
    poligono: dict | None = None
    ativo: bool = True


class TalhaoCreate(TalhaoBase):
    fazenda_id: uuid.UUID


class TalhaoUpdate(BaseModel):
    nome: str | None = None
    area_ha: float | None = None
    variedade: str | None = None
    ativo: bool | None = None


class TalhaoRead(TalhaoBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fazenda_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
