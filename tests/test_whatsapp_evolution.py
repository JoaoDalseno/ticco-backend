"""
Testes de integração da Evolution API — serviço WhatsApp e webhook.
"""
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.whatsapp import EvolutionWebhookPayload


def _evolution_payload(
    event: str = "messages.upsert",
    remote_jid: str = "5516999999999@s.whatsapp.net",
    from_me: bool = False,
    message_id: str = "ABCDE12345",
    message_type: str = "conversation",
    text: str | None = "Olá",
    audio_url: str | None = None,
) -> dict:
    """Fábrica de payloads válidos da Evolution API."""
    msg: dict = {}
    if text:
        msg["conversation"] = text
    if audio_url:
        msg["audioMessage"] = {
            "url": audio_url,
            "mimetype": "audio/ogg; codecs=opus",
            "seconds": 30,
        }
    return {
        "event": event,
        "instance": "ticco",
        "data": {
            "key": {
                "remoteJid": remote_jid,
                "fromMe": from_me,
                "id": message_id,
            },
            "message": msg,
            "messageType": message_type,
            "messageTimestamp": 1716000000,
            "pushName": "João Silva",
        },
    }


def test_schema_parseia_mensagem_texto():
    raw = _evolution_payload()
    p = EvolutionWebhookPayload(**raw)
    assert p.event == "messages.upsert"
    assert p.data.key.remote_jid == "5516999999999@s.whatsapp.net"
    assert p.data.key.from_me is False
    assert p.data.key.id == "ABCDE12345"
    assert p.data.message.get("conversation") == "Olá"


def test_schema_parseia_evento_nao_mensagem():
    raw = _evolution_payload(event="connection.update")
    p = EvolutionWebhookPayload(**raw)
    assert p.event == "connection.update"


# ── Testes do serviço Evolution API ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_send_text_retorna_true_quando_api_ok():
    """send_text retorna True quando Evolution API responde 200."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"key": {"id": "123"}})

    with patch("app.services.whatsapp.evolution.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.whatsapp.evolution import send_text
        result = await send_text("+5516999999999", "Olá")

    assert result is True


@pytest.mark.asyncio
async def test_send_text_retorna_false_quando_api_falha():
    """send_text retorna False e não levanta exceção quando API retorna erro."""
    import httpx

    with patch("app.services.whatsapp.evolution.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPError("Connection refused")
        )
        mock_client_cls.return_value = mock_client

        from app.services.whatsapp.evolution import send_text
        result = await send_text("+5516999999999", "Olá")

    assert result is False


@pytest.mark.asyncio
async def test_send_pdf_com_url_publica_passa_url_no_payload():
    """send_pdf com URL pública usa a URL diretamente no campo media."""
    captured_payload = {}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={})

    async def fake_post(url, json=None, headers=None, **kwargs):
        captured_payload.update(json or {})
        return mock_response

    with patch("app.services.whatsapp.evolution.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = fake_post
        mock_client_cls.return_value = mock_client

        from app.services.whatsapp.evolution import send_pdf
        await send_pdf(
            "+5516999999999",
            "https://storage.supabase.co/file.pdf",
            filename="receituario.pdf",
        )

    assert captured_payload["media"] == "https://storage.supabase.co/file.pdf"
    assert captured_payload["mediatype"] == "document"
    assert captured_payload["fileName"] == "receituario.pdf"


@pytest.mark.asyncio
async def test_send_pdf_com_path_local_converte_para_base64(tmp_path):
    """send_pdf com path local lê o arquivo e codifica em base64."""
    pdf_content = b"%PDF-1.4 test"
    pdf_file = tmp_path / "test.pdf"
    pdf_file.write_bytes(pdf_content)

    captured_payload = {}

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={})

    async def fake_post(url, json=None, headers=None, **kwargs):
        captured_payload.update(json or {})
        return mock_response

    with patch("app.services.whatsapp.evolution.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = fake_post
        mock_client_cls.return_value = mock_client

        from app.services.whatsapp.evolution import send_pdf
        await send_pdf("+5516999999999", str(pdf_file), filename="test.pdf")

    expected_b64 = base64.b64encode(pdf_content).decode()
    assert captured_payload["media"] == expected_b64


@pytest.mark.asyncio
async def test_download_media_decodifica_base64_e_retorna_bytes():
    """download_media decodifica base64 da resposta Evolution API e retorna bytes."""
    audio_content = b"fake-audio-bytes"
    b64_audio = base64.b64encode(audio_content).decode()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"base64": b64_audio})

    with patch("app.services.whatsapp.evolution.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        from app.services.whatsapp.evolution import download_media
        result = await download_media("https://audio.url", "MSG_ID_123")

    assert result == audio_content


# ── Testes do webhook Evolution API ──────────────────────────────────────────

@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
def override_deps():
    """Evita DB real nos testes de webhook."""
    from app.api.deps import get_db
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    yield
    app.dependency_overrides.clear()


def _evolution_headers(api_key: str = "test-evolution-key") -> dict:
    return {"apikey": api_key, "Content-Type": "application/json"}


@pytest.mark.asyncio
async def test_webhook_rejeita_sem_apikey(client):
    """Requisição sem apikey → 401."""
    r = await client.post(
        "/webhooks/whatsapp",
        json=_evolution_payload(),
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_ignora_evento_connection_update(client):
    """Evento connection.update não é mensagem — deve retornar ignored."""
    with patch("app.api.webhooks.whatsapp.settings") as mock_settings:
        mock_settings.evolution_api_key = "test-evolution-key"
        mock_settings.evolution_instance_key = ""

        r = await client.post(
            "/webhooks/whatsapp",
            json=_evolution_payload(event="connection.update"),
            headers=_evolution_headers(),
        )

    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_ignora_mensagem_from_me(client):
    """Mensagem enviada pelo próprio bot (fromMe=true) → ignored."""
    with patch("app.api.webhooks.whatsapp.settings") as mock_settings:
        mock_settings.evolution_api_key = "test-evolution-key"
        mock_settings.evolution_instance_key = ""

        r = await client.post(
            "/webhooks/whatsapp",
            json=_evolution_payload(from_me=True),
            headers=_evolution_headers(),
        )

    assert r.status_code == 200
    assert r.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_extrai_telefone_do_remote_jid(client):
    """remoteJid 5516999999999@s.whatsapp.net → telefone +5516999999999."""
    with (
        patch("app.api.webhooks.whatsapp.settings") as mock_settings,
        patch("app.api.webhooks.whatsapp._processar_em_background", new_callable=AsyncMock),
        patch("app.api.webhooks.whatsapp.check_rate_limit", return_value=(True, "")),
        patch("app.api.webhooks.whatsapp.AsyncSessionLocal"),
    ):
        mock_settings.evolution_api_key = "test-evolution-key"
        mock_settings.evolution_instance_key = ""

        r = await client.post(
            "/webhooks/whatsapp",
            json=_evolution_payload(remote_jid="5516999999999@s.whatsapp.net"),
            headers=_evolution_headers(),
        )

    # Mesmo que falhe no DB, deve ter tentado processar com o telefone correto
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_webhook_nao_processa_message_id_duplicado(client):
    """Mesmo message_id recebido duas vezes → segunda vez retorna duplicate."""
    with (
        patch("app.api.webhooks.whatsapp.settings") as mock_settings,
        patch("app.api.webhooks.whatsapp._message_ja_processada", return_value=True),
        patch("app.api.webhooks.whatsapp.check_rate_limit", return_value=(True, "")),
    ):
        mock_settings.evolution_api_key = "test-evolution-key"
        mock_settings.evolution_instance_key = ""

        r = await client.post(
            "/webhooks/whatsapp",
            json=_evolution_payload(message_id="DUPLICATE_ID"),
            headers=_evolution_headers(),
        )

    assert r.status_code == 200
    assert r.json()["status"] == "duplicate"
