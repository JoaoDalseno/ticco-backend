"""
Cliente HTTP para a Evolution API (WhatsApp self-hosted).

Referência: https://doc.evolution-api.com/
"""
import base64
import logging

import httpx

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _mask(phone: str) -> str:
    """Mascara telefone para logs (LGPD)."""
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


def _normalize_phone(phone: str) -> str:
    """
    Normaliza telefone para formato Evolution API: somente dígitos, sem +.
    +5516999999999 → 5516999999999
    """
    return phone.replace("+", "").replace(" ", "").replace("-", "")


def _base_url() -> str:
    return settings.evolution_api_url.rstrip("/")


def _headers() -> dict[str, str]:
    return {
        "apikey": settings.evolution_api_key,
        "Content-Type": "application/json",
    }


# ── Funções públicas ──────────────────────────────────────────────────────────

async def send_text(phone: str, message: str) -> bool:
    """Envia mensagem de texto via Evolution API. Retorna True em sucesso."""
    url = f"{_base_url()}/message/sendText/{settings.evolution_instance}"
    payload = {
        "number": _normalize_phone(phone),
        "text": message,
    }
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            r = await client.post(url, json=payload, headers=_headers())
            r.raise_for_status()
            logger.info("[WHATSAPP] Texto enviado → %s", _mask(phone))
            return True
        except httpx.HTTPError as e:
            logger.error("[WHATSAPP] Erro ao enviar texto para %s: %s", _mask(phone), e)
            return False


async def send_pdf(
    phone: str,
    pdf_url: str,
    filename: str = "receituario.pdf",
    caption: str = "",
) -> bool:
    """
    Envia PDF como documento via Evolution API. Retorna True em sucesso.

    Se pdf_url for URL pública (http/https), usa direto no campo media.
    Se for path local, lê o arquivo e converte para base64.
    """
    url = f"{_base_url()}/message/sendMedia/{settings.evolution_instance}"

    if pdf_url.startswith("http://") or pdf_url.startswith("https://"):
        media: str = pdf_url
    else:
        with open(pdf_url, "rb") as f:
            media = base64.b64encode(f.read()).decode()

    payload = {
        "number": _normalize_phone(phone),
        "mediatype": "document",
        "mimetype": "application/pdf",
        "media": media,
        "fileName": filename,
        "caption": caption,
    }
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            r = await client.post(url, json=payload, headers=_headers())
            r.raise_for_status()
            logger.info("[WHATSAPP] PDF '%s' enviado → %s", filename, _mask(phone))
            return True
        except httpx.HTTPError as e:
            logger.error("[WHATSAPP] Erro ao enviar PDF para %s: %s", _mask(phone), e)
            return False


async def send_audio(phone: str, audio_url: str) -> bool:
    """Envia áudio via Evolution API. Retorna True em sucesso."""
    url = f"{_base_url()}/message/sendWhatsAppAudio/{settings.evolution_instance}"
    payload = {
        "number": _normalize_phone(phone),
        "audio": audio_url,
        "encoding": True,
    }
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        try:
            r = await client.post(url, json=payload, headers=_headers())
            r.raise_for_status()
            logger.info("[WHATSAPP] Áudio enviado → %s", _mask(phone))
            return True
        except httpx.HTTPError as e:
            logger.error("[WHATSAPP] Erro ao enviar áudio para %s: %s", _mask(phone), e)
            return False


async def send_image(phone: str, image_url: str, caption: str = "") -> bool:
    """Envia imagem via Evolution API. Retorna True em sucesso."""
    url = f"{_base_url()}/message/sendMedia/{settings.evolution_instance}"
    payload = {
        "number": _normalize_phone(phone),
        "mediatype": "image",
        "mimetype": "image/jpeg",
        "media": image_url,
        "caption": caption,
    }
    async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
        try:
            r = await client.post(url, json=payload, headers=_headers())
            r.raise_for_status()
            logger.info("[WHATSAPP] Imagem enviada → %s", _mask(phone))
            return True
        except httpx.HTTPError as e:
            logger.error("[WHATSAPP] Erro ao enviar imagem para %s: %s", _mask(phone), e)
            return False


async def download_media(media_url: str, message_id: str) -> bytes:
    """
    Baixa mídia de uma mensagem recebida pelo message_id via Evolution API.
    Levanta exceção se falhar (o pipeline precisa saber).
    """
    url = (
        f"{_base_url()}/chat/getBase64FromMediaMessage"
        f"/{settings.evolution_instance}"
    )
    payload = {
        "message": {"key": {"id": message_id}},
        "convertToMp4": False,
    }
    async with httpx.AsyncClient(timeout=60.0, verify=False) as client:
        r = await client.post(url, json=payload, headers=_headers())
        r.raise_for_status()
        data = r.json()
        b64 = (
            data.get("base64")
            or (data.get("data") or {}).get("base64", "")
        )
        if not b64:
            raise ValueError(
                f"[WHATSAPP] base64 não encontrado na resposta para message_id={message_id}"
            )
        logger.info(
            "[WHATSAPP] Mídia baixada via Evolution API — message_id=%s", message_id
        )
        return base64.b64decode(b64)


# ── Classe wrapper (mantém interface igual à ZAPIWhatsAppService) ─────────────

class EvolutionWhatsAppService:
    """Wrapper em classe para injeção de dependência no worker."""

    async def send_text(self, phone: str, message: str) -> bool:
        return await send_text(phone, message)

    async def send_pdf(
        self,
        phone: str,
        pdf_url: str,
        filename: str = "receituario.pdf",
        caption: str = "",
    ) -> bool:
        return await send_pdf(phone, pdf_url, filename=filename, caption=caption)

    # Alias de compatibilidade — callers que ainda usam send_document não quebram
    async def send_document(self, phone: str, document_url: str, filename: str) -> bool:
        return await send_pdf(phone, document_url, filename=filename)

    async def send_audio(self, phone: str, audio_url: str) -> bool:
        return await send_audio(phone, audio_url)

    async def send_image(self, phone: str, image_url: str, caption: str = "") -> bool:
        return await send_image(phone, image_url, caption=caption)

    async def download_media(self, media_url: str, message_id: str) -> bytes:
        return await download_media(media_url, message_id)
