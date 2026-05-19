"""
Emissão de tokens JWT pros agrônomos.

Por enquanto só o admin do dashboard emite token (em nome do agrônomo).
Quando houver portal próprio do agrônomo, trocar por OTP via WhatsApp.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.admin import _verificar_admin
from app.api.deps import get_db
from app.config import settings
from app.core.security import criar_access_token
from app.models.agronomo import Agronomo

router = APIRouter(prefix="/v1/auth", tags=["auth"])


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class IssueTokenRequest(BaseModel):
    agronomo_id: uuid.UUID


@router.post("/issue-token", response_model=TokenResponse)
async def issue_token(
    body: IssueTokenRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
) -> TokenResponse:
    """Emite um JWT em nome do agrônomo informado. Protegido por X-Admin-Key."""
    agronomo = await db.get(Agronomo, body.agronomo_id)
    if agronomo is None:
        raise HTTPException(status_code=404, detail="Agrônomo não encontrado")

    return TokenResponse(
        access_token=criar_access_token(agronomo.id),
        expires_in_minutes=settings.jwt_expire_minutes,
    )
