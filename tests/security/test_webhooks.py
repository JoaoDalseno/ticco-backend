"""
Testes de segurança — Webhooks externos.

Cobre TICCO-SEC-001 (ClickSign HMAC) e validações de token Z-API / Stripe.
OWASP A08 — Software/Data Integrity Failures
OWASP A07 — Identification and Authentication Failures

Para rodar: pytest tests/security/test_webhooks.py -v
"""
import hashlib
import hmac
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import patch

from app.main import app


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ============================================================
# ClickSign — HMAC-SHA256 (TICCO-SEC-001, Critical)
# ============================================================

@pytest.mark.asyncio
async def test_clicksign_rejeita_hmac_ausente_quando_secret_configurado(client):
    """Deve retornar 401 se Content-Hmac não vier e secret estiver configurado. A08."""
    with patch("app.api.webhooks.clicksign.settings") as mock_settings:
        mock_settings.clicksign_webhook_secret = "meu-segredo-teste"

        payload = b'{"event": {"name": "sign"}, "document": {"key": "doc-abc"}}'
        r = await client.post(
            "/webhooks/clicksign",
            content=payload,
            headers={"Content-Type": "application/json"},
        )
    assert r.status_code == 401, f"Esperado 401, recebido {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_clicksign_rejeita_hmac_invalido(client):
    """Deve retornar 401 se o HMAC não bater com o secret. A08."""
    with patch("app.api.webhooks.clicksign.settings") as mock_settings:
        mock_settings.clicksign_webhook_secret = "meu-segredo-teste"

        payload = b'{"event": {"name": "sign"}, "document": {"key": "doc-abc"}}'
        r = await client.post(
            "/webhooks/clicksign",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Content-Hmac": "sha256=invalido",
            },
        )
    assert r.status_code == 401, f"Esperado 401, recebido {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_clicksign_aceita_hmac_valido(client):
    """Deve aceitar o request quando o HMAC for calculado corretamente. A08."""
    secret = "meu-segredo-teste"
    payload = json.dumps({"event": {"name": "evento_ignorado"}, "document": {}}).encode()
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    with patch("app.api.webhooks.clicksign.settings") as mock_settings:
        mock_settings.clicksign_webhook_secret = secret

        r = await client.post(
            "/webhooks/clicksign",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Content-Hmac": f"sha256={mac}",
            },
        )
    # Evento ignorado (not sign/auto_close) mas autenticado — retorna 200
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_clicksign_rejeita_hmac_adulterado(client):
    """Garante resistência a adulteração parcial do HMAC. A08."""
    secret = "meu-segredo-teste"
    payload = b'{"event": {"name": "sign"}}'
    mac = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    adulterado = mac[:-1] + ("a" if mac[-1] != "a" else "b")

    with patch("app.api.webhooks.clicksign.settings") as mock_settings:
        mock_settings.clicksign_webhook_secret = secret

        r = await client.post(
            "/webhooks/clicksign",
            content=payload,
            headers={
                "Content-Type": "application/json",
                "Content-Hmac": f"sha256={adulterado}",
            },
        )
    assert r.status_code == 401


# ============================================================
# Z-API (WhatsApp) — Security Token (pré-existente, regressão)
# ============================================================

@pytest.mark.asyncio
async def test_zapi_rejeita_token_ausente(client):
    """Sem header de autenticação → 401. A08."""
    r = await client.post(
        "/webhooks/whatsapp",
        json={"phone": "+5511999999999", "messageId": "msg-1"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_zapi_rejeita_token_errado(client):
    """Token incorreto → 401. A08."""
    with patch("app.api.webhooks.whatsapp.settings") as mock_settings:
        mock_settings.zapi_security_token = "token-correto"

        r = await client.post(
            "/webhooks/whatsapp",
            json={"phone": "+5511999999999"},
            headers={"X-Security-Token": "token-errado"},
        )
    assert r.status_code == 401


# ============================================================
# Stripe — assinatura ausente/inválida (regressão A08)
# ============================================================

@pytest.mark.asyncio
async def test_stripe_rejeita_sem_assinatura(client):
    """Request sem header stripe-signature → 400/401. A08."""
    r = await client.post(
        "/webhooks/stripe",
        content=b'{"type": "invoice.paid"}',
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code in (400, 401)


@pytest.mark.asyncio
async def test_stripe_rejeita_assinatura_invalida(client):
    """Assinatura forjada → 400/401. A08."""
    r = await client.post(
        "/webhooks/stripe",
        content=b'{"type": "invoice.paid"}',
        headers={
            "Content-Type": "application/json",
            "stripe-signature": "t=123,v1=invalido_completamente",
        },
    )
    assert r.status_code in (400, 401)


# ============================================================
# Body size limit (TICCO-SEC-004, High)
# ============================================================

@pytest.mark.asyncio
async def test_body_size_rejeita_31mb(client):
    """Payload de 31 MB com Content-Length → 413. A04."""
    big_payload = b"x" * (31 * 1024 * 1024)
    r = await client.post(
        "/webhooks/whatsapp",
        content=big_payload,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(big_payload)),
        },
    )
    assert r.status_code == 413


@pytest.mark.asyncio
async def test_body_size_aceita_payload_pequeno(client):
    """Payload pequeno não deve ser rejeitado pelo middleware de tamanho. A04."""
    small_payload = b'{"type": "test"}'
    r = await client.post(
        "/webhooks/stripe",
        content=small_payload,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code != 413
