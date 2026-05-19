"""
JWT — emissão e validação de tokens de acesso de agrônomo.

Tokens são HS256 assinados com `settings.jwt_secret` e carregam:
  sub: agronomo_id (UUID como string)
  exp: epoch UTC
  iat: epoch UTC
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

from app.config import settings


class TokenInvalidoError(Exception):
    """Token JWT ausente, expirado ou com assinatura inválida."""


def criar_access_token(agronomo_id: uuid.UUID) -> str:
    """Emite um JWT pro agrônomo. Validade = settings.jwt_expire_minutes."""
    agora = datetime.now(timezone.utc)
    payload = {
        "sub": str(agronomo_id),
        "iat": int(agora.timestamp()),
        "exp": int((agora + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decodificar_access_token(token: str) -> uuid.UUID:
    """Valida o token e retorna o agronomo_id. Levanta TokenInvalidoError em qualquer falha."""
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp"]},
        )
        return uuid.UUID(payload["sub"])
    except (InvalidTokenError, ValueError, KeyError) as exc:
        raise TokenInvalidoError(str(exc)) from exc
