"""
Webhook ClickSign — recebe notificações de assinatura de documentos.

Endpoint: POST /webhooks/clicksign

Eventos tratados:
  sign       → signatário assinou o documento
  auto_close → todos assinaram e o documento foi fechado automaticamente

Fluxo ao receber evento válido:
  1. Valida o payload (event.name in {"sign", "auto_close"})
  2. Busca Receituario pelo clicksign_envelope_key
  3. Baixa o PDF assinado via ClickSign API
  4. Faz upload pro Supabase Storage
  5. Atualiza Receituario no banco (pdf_assinado_url, status="assinado")

Sempre retorna 200 para evitar que a ClickSign reenvie o evento em loop.
"""
import logging

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.receituario import Receituario, StatusReceituarioEnum
from app.services.storage import StorageService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")

_storage = StorageService()
_CLICKSIGN_TIMEOUT = 30.0


@router.post("/clicksign")
async def webhook_clicksign(request: Request) -> dict:
    """
    Recebe eventos da ClickSign.
    Sempre retorna 200 para evitar reenvios infinitos.
    """
    try:
        payload = await request.json()
    except Exception as exc:
        logger.error("[ICP] Webhook ClickSign: payload inválido — %s", exc)
        return {"ok": True}

    event_name: str = (payload.get("event") or {}).get("name", "")

    if event_name not in {"sign", "auto_close"}:
        logger.debug("[ICP] Webhook ClickSign: evento ignorado — %s", event_name)
        return {"ok": True}

    document_data: dict = payload.get("document") or {}
    document_key: str | None = document_data.get("key")

    if not document_key:
        logger.warning("[ICP] Webhook ClickSign: document.key ausente no payload")
        return {"ok": True}

    logger.info(
        "[ICP] Webhook ClickSign: processando evento=%s document_key=%s",
        event_name,
        document_key,
    )

    try:
        async with AsyncSessionLocal() as db:
            await _processar_assinatura(document_key, document_data, db)
    except Exception as exc:
        logger.error(
            "[ICP] Erro ao processar webhook ClickSign (document_key=%s): %s",
            document_key,
            exc,
            exc_info=True,
        )

    return {"ok": True}


async def _processar_assinatura(
    document_key: str,
    document_data: dict,
    db: AsyncSession,
) -> None:
    """Baixa o PDF assinado e persiste no banco."""

    # 1. Busca o Receituario pelo envelope_key
    result = await db.execute(
        select(Receituario).where(
            Receituario.clicksign_envelope_key == document_key
        )
    )
    receituario = result.scalar_one_or_none()

    if not receituario:
        logger.warning(
            "[ICP] Webhook ClickSign: Receituario não encontrado para envelope_key=%s",
            document_key,
        )
        return

    numero_serie = receituario.numero_serie

    # 2. Tenta pegar a URL do PDF assinado diretamente no payload
    signed_file_url: str | None = (
        (document_data.get("downloads") or {}).get("signed_file_url")
    )

    # Se não veio no payload, busca via API
    if not signed_file_url:
        signed_file_url = await _buscar_pdf_assinado_url(document_key)

    if not signed_file_url:
        logger.error(
            "[ICP] Webhook ClickSign: signed_file_url não disponível para document_key=%s",
            document_key,
        )
        return

    # 3. Baixa o PDF assinado
    async with httpx.AsyncClient(timeout=_CLICKSIGN_TIMEOUT) as client:
        resp = await client.get(signed_file_url)
        resp.raise_for_status()
        pdf_bytes = resp.content

    # 4. Upload pro Supabase Storage
    storage_path = f"receituarios/{numero_serie}/receituario_assinado.pdf"
    pdf_assinado_url = await _storage.upload_pdf(path=storage_path, pdf_bytes=pdf_bytes)

    # 5. Atualiza o Receituario no banco
    receituario.pdf_assinado_url = pdf_assinado_url
    receituario.status = StatusReceituarioEnum.assinado
    await db.commit()

    logger.info(
        "[ICP] Receituário %s assinado com sucesso via ClickSign", numero_serie
    )


async def _buscar_pdf_assinado_url(document_key: str) -> str | None:
    """Consulta a API ClickSign para obter a URL do PDF assinado."""
    base_url = settings.clicksign_base_url.rstrip("/")
    token = settings.clicksign_api_key

    try:
        async with httpx.AsyncClient(timeout=_CLICKSIGN_TIMEOUT) as client:
            resp = await client.get(
                f"{base_url}/documents/{document_key}",
                params={"access_token": token},
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("document") or {}).get("downloads", {}).get("signed_file_url")
    except Exception as exc:
        logger.error(
            "[ICP] Erro ao buscar PDF assinado da ClickSign (key=%s): %s",
            document_key,
            exc,
        )
        return None
