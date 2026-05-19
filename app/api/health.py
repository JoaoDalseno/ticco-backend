import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    """Verifica status da API e conectividade com o banco. Retorna 503 se DB falha."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
        http_status = 200
    except Exception as exc:
        logger.error("Falha na conexao com o banco: %s", exc)
        db_status = "error"
        http_status = 503

    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ok" if http_status == 200 else "degraded",
            "database": db_status,
            "env": settings.app_env,
        },
    )
