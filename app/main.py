import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

from app.config import settings
from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.checkout import router as checkout_router
from app.api.v1.fazendas import router as fazendas_router
from app.api.webhooks.stripe import router as stripe_router
from app.api.webhooks.whatsapp import router as whatsapp_router
from app.core.rate_limiter import limiter

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

# Rate limiter (slowapi — por IP)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ticco.com.br", "https://ticco-henna.vercel.app", "http://localhost:3000"],
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["infra"])
app.include_router(whatsapp_router, tags=["webhooks"])
app.include_router(stripe_router, tags=["webhooks"])
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(checkout_router)
app.include_router(fazendas_router)
