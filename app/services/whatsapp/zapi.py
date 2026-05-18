"""
Cliente HTTP para a Z-API (WhatsApp).

Referência: https://developer.z-api.io/
"""
import httpx

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


def _base() -> str:
    return (
        f"{settings.zapi_base_url}/instances"
        f"/{settings.zapi_instance_id}/token/{settings.zapi_token}"
    )


def _headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if settings.zapi_security_token:
        h["Client-Token"] = settings.zapi_security_token
    return h


async def send_text(phone: str, message: str) -> dict:
    """Envia mensagem de texto via Z-API."""
    url = f"{_base()}/send-text"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json={"phone": phone, "message": message}, headers=_headers())
        resp.raise_for_status()
        logger.debug("Z-API send_text → %s", _mask(phone))
        return resp.json()


async def send_document(phone: str, document_url: str, filename: str) -> dict:
    """Envia documento PDF via Z-API."""
    url = f"{_base()}/send-document/pdf"
    payload = {"phone": phone, "document": document_url, "fileName": filename}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        logger.debug("Z-API send_document → %s: %s", _mask(phone), filename)
        return resp.json()


async def send_image(phone: str, image_url: str, caption: str = "") -> dict:
    """Envia imagem via Z-API."""
    url = f"{_base()}/send-image"
    payload = {"phone": phone, "image": image_url, "caption": caption}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload, headers=_headers())
        resp.raise_for_status()
        return resp.json()


class ZAPIWhatsAppService:
    """Wrapper em classe para uso no worker."""

    async def send_text(self, phone: str, message: str) -> dict:
        return await send_text(phone, message)

    async def send_document(self, phone: str, document_url: str, filename: str) -> dict:
        return await send_document(phone, document_url, filename)

    async def send_image(self, phone: str, image_url: str, caption: str = "") -> dict:
        return await send_image(phone, image_url, caption)
