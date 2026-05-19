"""Dependencies do FastAPI — DB e auth."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenInvalidoError, decodificar_access_token
from app.database import get_db as get_db  # noqa: F401 — re-export
from app.models.agronomo import Agronomo

_bearer = HTTPBearer(auto_error=False)


async def get_current_agronomo(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Agronomo:
    """Resolve o agrônomo autenticado a partir do header Authorization: Bearer <jwt>."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token ausente",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        agronomo_id = decodificar_access_token(credentials.credentials)
    except TokenInvalidoError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token inválido: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    agronomo = await db.get(Agronomo, agronomo_id)
    if agronomo is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Agrônomo do token não encontrado",
        )
    return agronomo
