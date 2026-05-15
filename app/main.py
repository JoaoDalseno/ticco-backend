import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.health import router as health_router
from app.api.webhooks.whatsapp import router as whatsapp_router
from app.api.webhooks.stripe import router as stripe_router

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Ticco API iniciando... env=%s", settings.app_env)
    yield
    logger.info("Ticco API encerrando.")


app = FastAPI(
    title="Ticco API",
    version="0.1.0",
    description="Backend da plataforma Ticco — gestão de consultoria cafeicultora via WhatsApp + IA",
    lifespan=lifespan,
    # Oculta /docs e /redoc em produção
    docs_url="/docs" if settings.app_env == "development" else None,
    redoc_url="/redoc" if settings.app_env == "development" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ticco.com.br", "https://ticco-henna.vercel.app", "http://localhost:3000"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["infra"])
app.include_router(whatsapp_router, tags=["webhooks"])
app.include_router(stripe_router, tags=["webhooks"])
