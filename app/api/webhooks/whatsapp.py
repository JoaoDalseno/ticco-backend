"""
Webhook Z-API — recebe eventos de mensagens do WhatsApp.

Endpoint: POST /webhooks/whatsapp

Fluxo:
  1. Valida Security Token (se configurado)
  2. Filtra apenas ReceivedCallback (mensagens recebidas, não enviadas)
  3. Salva Mensagem no banco
  4. Roteamento:
     a. Número em onboarding → continua onboarding
     b. Agrônomo cadastrado  → dispara process_message (Fase 4)
     c. Número desconhecido  → inicia onboarding
"""
import hmac
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.core.rate_limiter import check_rate_limit
from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo
from app.models.mensagem import DirecaoEnum, Mensagem, TipoEnum
from app.schemas.whatsapp import ZAPIWebhookPayload
from app.services.whatsapp import onboarding
from app.workers.process_message import process_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks")


def _mask(phone: str) -> str:
    """Mascara número para logs — evita PII (LGPD)."""
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _validar_security_token(client_token: str | None) -> None:
    """Rejeita requisições sem o token correto (quando configurado).
    Usa compare_digest para evitar timing attacks.
    """
    expected = settings.zapi_security_token
    if expected:
        if not client_token or not hmac.compare_digest(client_token, expected):
            raise HTTPException(status_code=401, detail="Security token inválido")


def _extrair_tipo_e_conteudo(payload: ZAPIWebhookPayload) -> tuple[TipoEnum, str | None, str | None]:
    """
    Retorna (tipo, conteudo_texto, midia_url) a partir do payload Z-API.
    """
    if payload.text:
        return TipoEnum.texto, payload.text.get("message"), None

    if payload.audio:
        return TipoEnum.audio, None, payload.audio.get("audioUrl")

    if payload.image:
        caption = payload.image.get("caption", "")
        return TipoEnum.imagem, caption or None, payload.image.get("imageUrl")

    if payload.document:
        return TipoEnum.documento, payload.document.get("fileName"), payload.document.get("documentUrl")

    return TipoEnum.texto, None, None


def _normalizar_phone(phone: str | None) -> str:
    """Garante formato E.164 (+55...)."""
    if not phone:
        return ""
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = f"+{phone}"
    return phone


# ── Background task ──────────────────────────────────────────────────────────

async def _processar_em_background(
    phone: str,
    texto: str | None,
    mensagem_id: uuid.UUID,
    agronomo_id: uuid.UUID | None,
) -> None:
    """Roteamento pós-persistência: onboarding ou pipeline de IA.
    Cria sessão própria para evitar uso de sessão encerrada da request.
    """
    async with AsyncSessionLocal() as db:
        try:
            if onboarding.em_onboarding(phone):
                await onboarding.processar_resposta(phone, texto, db)
                return

            if agronomo_id is None:
                await onboarding.iniciar(phone)
                return

            # Agrônomo cadastrado → pipeline IA
            await process_message(mensagem_id, db)

        except Exception:
            logger.exception("Erro no processamento background — phone=%s", _mask(phone))


# ── Endpoint ─────────────────────────────────────────────────────────────────

@router.post("/whatsapp")
async def webhook_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    client_token: str | None = Header(default=None, alias="Client-Token"),
) -> dict:
    _validar_security_token(client_token)

    raw = await request.json()

    try:
        payload = ZAPIWebhookPayload(**raw)
    except Exception:
        logger.warning("Payload Z-API inválido: %s", raw)
        return {"ok": True}

    # Ignora mensagens enviadas pelo próprio bot e callbacks de status
    if payload.fromMe or payload.type != "ReceivedCallback":
        return {"ok": True}

    phone = _normalizar_phone(payload.phone)
    if not phone:
        return {"ok": True}

    # ── Rate limit por telefone ───────────────────────────────────────────────
    allowed, motivo = check_rate_limit(phone)
    if not allowed:
        # Não responde ao usuário — evita loop de feedback
        logger.warning("Mensagem bloqueada por rate limit — phone=%s motivo=%s", _mask(phone), motivo)
        return {"status": "rate_limited"}

    tipo, conteudo_texto, midia_url = _extrair_tipo_e_conteudo(payload)

    # ── Busca agrônomo ────────────────────────────────────────────────────────
    resultado = await db.execute(
        select(Agronomo).where(Agronomo.telefone_wpp == phone)
    )
    agronomo = resultado.scalar_one_or_none()

    # ── Persiste mensagem ─────────────────────────────────────────────────────
    mensagem = Mensagem(
        id=uuid.uuid4(),
        agronomo_id=agronomo.id if agronomo else None,
        telefone_origem=phone,
        direcao=DirecaoEnum.recebida,
        tipo=tipo,
        conteudo_texto=conteudo_texto,
        midia_url=midia_url,
        zapi_message_id=payload.messageId,
        raw_payload=raw,
        processada=False,
    )
    db.add(mensagem)
    await db.commit()
    await db.refresh(mensagem)

    logger.info(
        "Mensagem recebida — phone=%s tipo=%s agronomo=%s",
        _mask(phone), tipo.value, agronomo.nome if agronomo else "desconhecido",
    )

    # ── Processamento assíncrono — nova sessão de DB criada internamente ──────
    background_tasks.add_task(
        _processar_em_background,
        phone=phone,
        texto=conteudo_texto,
        mensagem_id=mensagem.id,
        agronomo_id=agronomo.id if agronomo else None,
    )

    return {"ok": True}
