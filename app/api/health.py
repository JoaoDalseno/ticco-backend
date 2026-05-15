import logging

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)) -> dict:
    """Verifica status da API e conectividade com o banco de dados."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as exc:
        logger.error("Falha na conexao com o banco: %s", exc)
        db_status = "error"

    return {
        "status": "ok",
        "database": db_status,
        "env": settings.app_env,
    }
