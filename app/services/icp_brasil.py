"""
Serviço de assinatura digital ICP-Brasil via ClickSign.

Controlado por feature flag:
  ICP_BRASIL_ENABLED=false → modo mock (SHA-256 local + upload do PDF original)
  ICP_BRASIL_ENABLED=true  → fluxo completo ClickSign API v1

A interface pública (ICPBrasilService.gerar_numero_serie / .assinar) é
preservada para retrocompatibilidade com o código existente.
"""
import base64
import hashlib
import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

_storage = StorageService()

_CLICKSIGN_TIMEOUT = 30.0  # segundos


# ── Interface legada (retrocompatibilidade) ───────────────────────────────────

class ICPBrasilService:
    """Gera metadados de assinatura digital — mantida para código legado."""

    def gerar_numero_serie(self, visita_id: uuid.UUID) -> str:
        """Retorna número de série único para o receituário."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        sufixo = str(visita_id).replace("-", "")[:8].upper()
        return f"REC-{timestamp}-{sufixo}"

    def assinar(self, conteudo: bytes, crea: str) -> dict:
        """
        Simula assinatura digital do documento (modo mock legado).

        Returns:
            dict com hash, timestamp e fingerprint do "certificado".
        """
        hash_doc = hashlib.sha256(conteudo).hexdigest()
        return {
            "algoritmo": "SHA256withRSA",
            "hash_documento": hash_doc,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "titular_crea": crea,
            "certificado_serie": f"MOCK-{hash_doc[:16].upper()}",
            "valido": True,
        }


# ── Nova interface: assinar_receituario ───────────────────────────────────────

async def assinar_receituario(
    pdf_path: str,
    agronomo_cpf: str,
    agronomo_nome: str,
    agronomo_email: str,
    numero_serie: str,
) -> dict:
    """
    Envia receituário para assinatura digital.

    Quando ICP_BRASIL_ENABLED=False → mock local (hash + upload do original).
    Quando ICP_BRASIL_ENABLED=True  → fluxo ClickSign API v1 completo.

    Se a chamada à ClickSign falhar por qualquer motivo, faz fallback automático
    para o mock para garantir que o receituário seja sempre entregue.

    Args:
        pdf_path:      Caminho local do PDF gerado pelo WeasyPrint.
        agronomo_cpf:  CPF do agrônomo signatário.
        agronomo_nome: Nome completo do agrônomo.
        agronomo_email: E-mail do agrônomo (usado pela ClickSign para notificação).
        numero_serie:  Número de série do receituário (ex: REC-20260101120000-ABCD1234).

    Returns:
        {
            "pdf_assinado_url":        str,        # URL pública no Supabase Storage
            "hash_assinatura":         str,        # SHA-256 do PDF ou envelope_key da ClickSign
            "status":                  str,        # "mock" | "pendente" | "assinado"
            "clicksign_envelope_key":  str | None,
            "clicksign_signer_key":    str | None,
        }
    """
    with open(pdf_path, "rb") as fh:
        pdf_bytes = fh.read()

    if not settings.icp_brasil_enabled:
        return await _assinar_mock(pdf_bytes, numero_serie)

    try:
        return await _assinar_clicksign(
            pdf_bytes=pdf_bytes,
            agronomo_cpf=agronomo_cpf,
            agronomo_nome=agronomo_nome,
            agronomo_email=agronomo_email,
            numero_serie=numero_serie,
        )
    except Exception as exc:
        logger.error(
            "[ICP] Falha na ClickSign — fallback para mock. numero_serie=%s erro=%s",
            numero_serie,
            exc,
            exc_info=True,
        )
        return await _assinar_mock(pdf_bytes, numero_serie)


# ── Modo mock ─────────────────────────────────────────────────────────────────

async def _assinar_mock(pdf_bytes: bytes, numero_serie: str) -> dict:
    """Hash local + upload do PDF original. Sem chamada externa."""
    hash_doc = hashlib.sha256(pdf_bytes).hexdigest()

    storage_path = f"receituarios/{numero_serie}/receituario_mock.pdf"
    pdf_url = await _storage.upload_pdf(path=storage_path, pdf_bytes=pdf_bytes)

    logger.info("[ICP] Modo mock ativo — assinatura simulada para %s", numero_serie)

    return {
        "pdf_assinado_url": pdf_url,
        "hash_assinatura": hash_doc,
        "status": "mock",
        "clicksign_envelope_key": None,
        "clicksign_signer_key": None,
    }


# ── Modo ClickSign real ───────────────────────────────────────────────────────

async def _assinar_clicksign(
    pdf_bytes: bytes,
    agronomo_cpf: str,
    agronomo_nome: str,
    agronomo_email: str,
    numero_serie: str,
) -> dict:
    """Fluxo completo ClickSign API v1: upload → signer → list → notify."""
    base_url = settings.clicksign_base_url.rstrip("/")
    token = settings.clicksign_api_key
    content_b64 = base64.b64encode(pdf_bytes).decode()

    async with httpx.AsyncClient(timeout=_CLICKSIGN_TIMEOUT) as client:

        # Passo 1 — Upload do documento
        resp = await client.post(
            f"{base_url}/documents",
            params={"access_token": token},
            json={
                "document": {
                    "path": f"/ticco/receituarios/{numero_serie}.pdf",
                    "content_base64": content_b64,
                    "deadline_at": None,
                    "auto_close": True,
                    "locale": "pt-BR",
                    "sequence_enabled": False,
                }
            },
        )
        resp.raise_for_status()
        document_key: str = resp.json()["document"]["key"]
        logger.info("[ICP] Documento criado na ClickSign: key=%s", document_key)

        # Passo 2 — Criar signatário
        resp = await client.post(
            f"{base_url}/signers",
            params={"access_token": token},
            json={
                "signer": {
                    "email": agronomo_email,
                    "phone_number": "",
                    "auths": ["email"],
                    "name": agronomo_nome,
                    "documentation": agronomo_cpf,
                    "birthday": None,
                    "has_documentation": True,
                }
            },
        )
        resp.raise_for_status()
        signer_key: str = resp.json()["signer"]["key"]
        logger.info("[ICP] Signatário criado na ClickSign: key=%s", signer_key)

        # Passo 3 — Associar signatário ao documento
        resp = await client.post(
            f"{base_url}/lists",
            params={"access_token": token},
            json={
                "list": {
                    "document_key": document_key,
                    "signer_key": signer_key,
                    "sign_as": "sign",
                    "message": (
                        f"Por favor, assine o receituário agronômico "
                        f"#{numero_serie} gerado pelo Ticco."
                    ),
                }
            },
        )
        resp.raise_for_status()

        # Passo 4 — Notificar signatário por e-mail
        resp = await client.post(
            f"{base_url}/notifications",
            params={"access_token": token},
            json={
                "message": {
                    "document_key": document_key,
                    "signer_key": signer_key,
                    "message": (
                        f"Seu receituário agronômico #{numero_serie} "
                        f"está pronto para assinatura digital ICP-Brasil."
                    ),
                }
            },
        )
        resp.raise_for_status()

    # Upload do PDF original enquanto aguarda assinatura (será substituído via webhook)
    storage_path = f"receituarios/{numero_serie}/receituario_pendente.pdf"
    pdf_url = await _storage.upload_pdf(path=storage_path, pdf_bytes=pdf_bytes)

    logger.info(
        "[ICP] Envelope criado na ClickSign: %s para %s", document_key, numero_serie
    )

    return {
        "pdf_assinado_url": pdf_url,
        "hash_assinatura": document_key,
        "status": "pendente",
        "clicksign_envelope_key": document_key,
        "clicksign_signer_key": signer_key,
    }
