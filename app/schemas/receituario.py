import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.receituario import StatusReceituarioEnum


class ReceituarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    visita_id: uuid.UUID
    numero_serie: str
    produtos: list
    hash_assinatura: str | None
    pdf_assinado_url: str | None
    enviado_para_revenda: bool
    status: StatusReceituarioEnum
    created_at: datetime
    updated_at: datetime
