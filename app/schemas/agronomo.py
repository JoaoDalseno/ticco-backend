import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.agronomo import PlanoEnum, StatusPagamentoEnum


class AgronomoBase(BaseModel):
    nome: str = Field(..., min_length=2, max_length=200)
    cpf: str = Field(..., pattern=r"^\d{11}$", description="CPF apenas dígitos")
    crea: str = Field(..., max_length=50)
    telefone_wpp: str = Field(..., pattern=r"^\+55\d{10,11}$", description="E.164")
    email: EmailStr | None = None
    certificado_icp_url: str | None = None


class AgronomoCreate(AgronomoBase):
    pass


class AgronomoUpdate(BaseModel):
    nome: str | None = None
    email: EmailStr | None = None
    crea: str | None = None
    plano: PlanoEnum | None = None
    status_pagamento: StatusPagamentoEnum | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None


class AgronomoRead(AgronomoBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plano: PlanoEnum
    status_pagamento: StatusPagamentoEnum
    trial_ate: datetime | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    created_at: datetime
    updated_at: datetime
