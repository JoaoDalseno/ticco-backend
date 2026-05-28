import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import settings
from app.api.admin import router as admin_router
from app.api.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.checkout import router as checkout_router
from app.api.v1.fazendas import router as fazendas_router
from app.api.webhooks.clicksign import router as clicksign_router
from app.api.webhooks.stripe import router as stripe_router
from app.api.webhooks.whatsapp import router as whatsapp_router
from app.core.rate_limiter import limiter

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger(__name__)

_IS_PRODUCTION = settings.app_env == "production"

# ── CORS origins por environment ───────────────────────────────────────────────
_CORS_ORIGINS: list[str] = (
    ["https://ticco.com.br", "https://ticco-henna.vercel.app"]
    if _IS_PRODUCTION
    else ["https://ticco.com.br", "https://ticco-henna.vercel.app", "http://localhost:3000"]
)


# ── Middleware: security headers (A05 — Misconfiguration) ─────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adiciona headers de segurança HTTP em todas as respostas."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Server"] = "Ticco"
        if _IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )
        return response


# ── Middleware: limite de tamanho de body (A04 — Insecure Design) ─────────────
_MAX_BODY_BYTES = 30 * 1024 * 1024  # 30 MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejeita requests com Content-Length acima de 30 MB."""

    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_BODY_BYTES:
            logger.warning(
                "[SECURITY] Body rejeitado: Content-Length=%s ip=%s path=%s",
                content_length,
                request.client.host if request.client else "unknown",
                request.url.path,
            )
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
        return await call_next(request)


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
    # Oculta /docs, /redoc e /openapi.json em produção (A05 — Misconfiguration)
    docs_url="/docs" if not _IS_PRODUCTION else None,
    redoc_url="/redoc" if not _IS_PRODUCTION else None,
    openapi_url="/openapi.json" if not _IS_PRODUCTION else None,
)

# Rate limiter (slowapi — por IP)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ── Global exception handler — sem stacktrace em produção (A09 — Logging) ──────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = str(uuid.uuid4())
    logger.exception(
        "[UNHANDLED] error_id=%s path=%s method=%s — %s",
        error_id,
        request.url.path,
        request.method,
        exc,
    )
    if _IS_PRODUCTION:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "error_id": error_id},
        )
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "error_id": error_id, "type": type(exc).__name__},
    )


# Ordem importa: BodySizeLimit → SecurityHeaders → CORS
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["infra"])
app.include_router(whatsapp_router, tags=["webhooks"])
app.include_router(stripe_router, tags=["webhooks"])
app.include_router(clicksign_router, tags=["webhooks"])
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(checkout_router)
app.include_router(fazendas_router)
