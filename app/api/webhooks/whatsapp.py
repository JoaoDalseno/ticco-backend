"""
Webhook Evolution API — recebe eventos de mensagens do WhatsApp.

Endpoint: POST /webhooks/whatsapp

Fluxo:
  1. Valida apikey no header
  2. Filtra apenas events "messages.upsert"
  3. Ignora mensagens fromMe
  4. Extrai telefone e tipo de mensagem do payload Evolution API
  5. Verifica idempotência pelo message_id
  6. Verifica rate limit por telefone
  7. Salva Mensagem no banco
  8. Roteia: onboarding | pipeline IA
"""
import asyncio
import hmac
import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.core.rate_limiter import check_rate_limit
from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo
from app.models.mensagem import DirecaoEnum, Mensagem, TipoEnum
from app.schemas.whatsapp import EvolutionWebhookPayload
from app.services.whatsapp import onboarding
from app.workers.process_message import process_message

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")


def _mask(phone: str) -> str:
    """Mascara número para logs — evita PII (LGPD)."""
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


def _validar_origem_ip(client_ip: str | None) -> None:
    """
    Valida o IP de origem da requisição (header 'x-real-ip') contra
    settings.evolution_webhook_ip (lida da env var EVOLUTION_WEBHOOK_IP).
    Se a env var estiver vazia, aceita qualquer requisição.
    Usa hmac.compare_digest para evitar timing attacks.
    """
    expected = settings.evolution_webhook_ip
    if not expected:
        return
    if not client_ip or not hmac.compare_digest(client_ip, expected):
        logger.warning(
            "[WEBHOOK] Requisição recebida de IP não autorizado: %s", client_ip
        )
        raise HTTPException(status_code=401, detail="Unauthorized")


def _extrair_tipo_e_conteudo(
    msg: dict, message_type: str
) -> tuple[TipoEnum, str | None, str | None]:
    """
    Extrai (tipo, conteudo_texto, midia_url) do dict `message` da Evolution API.
    """
    # Texto simples
    if "conversation" in msg:
        return TipoEnum.texto, msg["conversation"], None

    # Texto longo (extendedTextMessage)
    if "extendedTextMessage" in msg:
        return TipoEnum.texto, msg["extendedTextMessage"].get("text"), None

    # Áudio
    if "audioMessage" in msg:
        return TipoEnum.audio, None, msg["audioMessage"].get("url")

    # Imagem
    if "imageMessage" in msg:
        caption = msg["imageMessage"].get("caption", "")
        return TipoEnum.imagem, caption or None, msg["imageMessage"].get("url")

    # Documento/PDF
    if "documentMessage" in msg:
        filename = msg["documentMessage"].get("fileName")
        return TipoEnum.documento, filename, msg["documentMessage"].get("url")

    return TipoEnum.texto, None, None


async def _message_ja_processada(db: AsyncSession, message_id: str) -> bool:
    """Verifica idempotência: retorna True se message_id já foi processado."""
    result = await db.execute(
        select(Mensagem.id).where(Mensagem.zapi_message_id == message_id)
    )
    return result.scalar_one_or_none() is not None


async def _processar_em_background(
    phone: str,
    texto: str | None,
    mensagem_id: uuid.UUID,
    agronomo_id: uuid.UUID | None,
) -> None:
    """Roteamento pós-persistência: onboarding ou pipeline de IA."""
    async with AsyncSessionLocal() as db:
        try:
            if onboarding.em_onboarding(phone):
                await onboarding.processar_resposta(phone, texto, db)
                return

            if agronomo_id is None:
                await onboarding.iniciar(phone)
                return

            await process_message(mensagem_id, db)

        except Exception:
            logger.exception(
                "[WEBHOOK] Erro no processamento background — phone=%s", _mask(phone)
            )


@router.post("/whatsapp")
async def webhook_whatsapp(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # 1. Validar IP de origem
    client_ip = request.headers.get("x-real-ip")
    _validar_origem_ip(client_ip)

    raw = await request.json()

    # 2. Parsear payload
    try:
        payload = EvolutionWebhookPayload(**raw)
    except Exception:
        logger.warning("[WEBHOOK] Payload Evolution API inválido: %s", str(raw)[:200])
        return {"ok": True}

    # 3. Filtrar — só processar mensagens recebidas
    if payload.event != "messages.upsert":
        return {"status": "ignored", "event": payload.event}

    data = payload.data
    if data.key.from_me:
        return {"status": "ignored", "reason": "fromMe"}

    # 4. Extrair telefone — remoteJid: "5516999999999@s.whatsapp.net"
    remote_jid = data.key.remote_jid

    # Ignora mensagens de grupos (remoteJid termina com @g.us)
    if remote_jid.endswith("@g.us"):
        logger.info("[WEBHOOK] Mensagem de grupo ignorada — jid=%s", remote_jid[:20])
        return {"status": "ignored", "reason": "group_message"}

    phone_digits = remote_jid.split("@")[0]
    if not phone_digits:
        return {"ok": True}
    phone = f"+{phone_digits}"

    message_id = data.key.id

    # 5. Idempotência — não processar mesmo message_id 2x
    if message_id and await _message_ja_processada(db, message_id):
        logger.info("[WEBHOOK] message_id=%s já processado — ignorando", message_id)
        return {"status": "duplicate"}

    # 6. Rate limit por telefone
    allowed, motivo = check_rate_limit(phone)
    if not allowed:
        logger.warning(
            "[WEBHOOK] Rate limit — phone=%s motivo=%s", _mask(phone), motivo
        )
        return {"status": "rate_limited"}

    tipo, conteudo_texto, midia_url = _extrair_tipo_e_conteudo(
        data.message, data.message_type
    )

    # 7. Busca agrônomo
    resultado = await db.execute(
        select(Agronomo).where(Agronomo.telefone_wpp == phone)
    )
    agronomo = resultado.scalar_one_or_none()

    # 8. Persiste mensagem
    mensagem = Mensagem(
        id=uuid.uuid4(),
        agronomo_id=agronomo.id if agronomo else None,
        telefone_origem=phone,
        direcao=DirecaoEnum.recebida,
        tipo=tipo,
        conteudo_texto=conteudo_texto,
        midia_url=midia_url,
        zapi_message_id=message_id,   # reutiliza coluna para Evolution message_id
        raw_payload=raw,
        processada=False,
    )
    db.add(mensagem)
    await db.commit()
    await db.refresh(mensagem)

    logger.info(
        "[WEBHOOK] Mensagem recebida — phone=%s tipo=%s agronomo=%s",
        _mask(phone),
        tipo.value,
        agronomo.nome if agronomo else "desconhecido",
    )

    # 9. Processamento assíncrono
    background_tasks.add_task(
        _processar_em_background,
        phone=phone,
        texto=conteudo_texto,
        mensagem_id=mensagem.id,
        agronomo_id=agronomo.id if agronomo else None,
    )

    return {"ok": True}
