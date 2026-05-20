"""
Testes para:
  - app/api/v1/checkout.py  (endpoint de checkout Stripe)
  - app/api/webhooks/stripe.py :: _handle_payment_succeeded (5º evento)
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _agronomo(stripe_customer_id=None, email="joao@fazenda.com"):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.nome = "João Agrônomo"
    a.email = email
    a.stripe_customer_id = stripe_customer_id
    a.plano = MagicMock()
    a.plano.value = "basico"
    return a


def _settings_patch(
    stripe_secret_key="sk_test_fake",
    stripe_price_basico="price_basico_fake",
    stripe_price_completo="price_completo_fake",
    frontend_url="https://ticco.com.br",
):
    mock = MagicMock()
    mock.stripe_secret_key = stripe_secret_key
    mock.stripe_price_basico = stripe_price_basico
    mock.stripe_price_completo = stripe_price_completo
    mock.frontend_url = frontend_url
    return mock


# ── _price_id_para_plano ──────────────────────────────────────────────────────


def test_price_id_basico_retorna_corretamente():
    from app.api.v1.checkout import _price_id_para_plano
    from fastapi import HTTPException

    with patch("app.api.v1.checkout.settings", _settings_patch()):
        price_id = _price_id_para_plano("basico")
    assert price_id == "price_basico_fake"


def test_price_id_completo_retorna_corretamente():
    from app.api.v1.checkout import _price_id_para_plano

    with patch("app.api.v1.checkout.settings", _settings_patch()):
        price_id = _price_id_para_plano("completo")
    assert price_id == "price_completo_fake"


def test_price_id_nao_configurado_levanta_503():
    from app.api.v1.checkout import _price_id_para_plano
    from fastapi import HTTPException

    with patch("app.api.v1.checkout.settings", _settings_patch(stripe_price_basico="")):
        with pytest.raises(HTTPException) as exc_info:
            _price_id_para_plano("basico")
    assert exc_info.value.status_code == 503


# ── _get_or_create_customer ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reutiliza_customer_existente():
    from app.api.v1.checkout import _get_or_create_customer

    agronomo = _agronomo(stripe_customer_id="cus_existente_123")
    mock_db = AsyncMock()

    with patch("app.api.v1.checkout.settings", _settings_patch()):
        result = await _get_or_create_customer(agronomo, mock_db)

    assert result == "cus_existente_123"
    mock_db.commit.assert_not_awaited()  # não precisa salvar nada


@pytest.mark.asyncio
async def test_cria_customer_novo_e_persiste():
    from app.api.v1.checkout import _get_or_create_customer

    agronomo = _agronomo(stripe_customer_id=None)
    mock_db = AsyncMock()

    fake_customer = MagicMock()
    fake_customer.id = "cus_novo_456"

    with (
        patch("app.api.v1.checkout.settings", _settings_patch()),
        patch("app.api.v1.checkout.asyncio.to_thread", AsyncMock(return_value=fake_customer)),
    ):
        result = await _get_or_create_customer(agronomo, mock_db)

    assert result == "cus_novo_456"
    assert agronomo.stripe_customer_id == "cus_novo_456"
    mock_db.commit.assert_awaited_once()


# ── _criar_checkout_session ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_criar_checkout_session_retorna_url():
    from app.api.v1.checkout import _criar_checkout_session

    fake_session = MagicMock()
    fake_session.id = "cs_test_abc"
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_abc"

    with (
        patch("app.api.v1.checkout.settings", _settings_patch()),
        patch("app.api.v1.checkout.asyncio.to_thread", AsyncMock(return_value=fake_session)),
    ):
        url = await _criar_checkout_session(
            customer_id="cus_123",
            price_id="price_basico_fake",
            agronomo_id="agr-uuid-here",
        )

    assert url == "https://checkout.stripe.com/pay/cs_test_abc"


@pytest.mark.asyncio
async def test_criar_checkout_url_contem_frontend():
    """success_url e cancel_url devem usar o frontend_url configurado."""
    from app.api.v1.checkout import _criar_checkout_session

    fake_session = MagicMock()
    fake_session.id = "cs_test_xyz"
    fake_session.url = "https://checkout.stripe.com/pay/cs_test_xyz"

    capturado = {}

    async def mock_to_thread(fn, **kwargs):
        capturado.update(kwargs)
        return fake_session

    with (
        patch("app.api.v1.checkout.settings", _settings_patch(frontend_url="https://meusite.com")),
        patch("app.api.v1.checkout.asyncio.to_thread", side_effect=mock_to_thread),
    ):
        await _criar_checkout_session("cus_1", "price_1", "agr_1")

    assert "https://meusite.com/sucesso" in capturado.get("success_url", "")
    assert "https://meusite.com" in capturado.get("cancel_url", "")


# ── invoice.payment_succeeded ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_payment_succeeded_reativa_conta_past_due():
    """Agrônomo past_due que paga deve ser reativado para active."""
    from app.api.webhooks.stripe import _handle_payment_succeeded
    from app.models.agronomo import StatusPagamentoEnum

    agronomo = _agronomo()
    agronomo.status_pagamento = StatusPagamentoEnum.past_due
    agronomo.telefone_wpp = "+5516999990001"

    mock_db = AsyncMock()

    event = MagicMock()
    event.data.object.get = lambda key, *a: "cus_test_123" if key == "customer" else None

    mock_wpp = AsyncMock()
    mock_wpp.send_text = AsyncMock()

    with (
        patch(
            "app.api.webhooks.stripe._buscar_agronomo_por_customer",
            AsyncMock(return_value=agronomo),
        ),
        patch("app.api.webhooks.stripe._atualizar_status", AsyncMock()) as mock_atualizar,
        patch("app.api.webhooks.stripe.whatsapp", mock_wpp),
    ):
        await _handle_payment_succeeded(event, mock_db)

    mock_atualizar.assert_awaited_once_with(agronomo, StatusPagamentoEnum.active, mock_db)
    mock_wpp.send_text.assert_awaited_once()
    _, msg = mock_wpp.send_text.call_args.args
    assert "✅" in msg


@pytest.mark.asyncio
async def test_payment_succeeded_renovacao_normal_nao_envia_wpp():
    """Renovação de conta active não deve enviar WhatsApp (evitar ruído mensal)."""
    from app.api.webhooks.stripe import _handle_payment_succeeded
    from app.models.agronomo import StatusPagamentoEnum

    agronomo = _agronomo()
    agronomo.status_pagamento = StatusPagamentoEnum.active
    agronomo.telefone_wpp = "+5516999990001"

    mock_db = AsyncMock()
    event = MagicMock()
    event.data.object.get = lambda key, *a: "cus_test_123" if key == "customer" else None

    mock_wpp = AsyncMock()
    mock_wpp.send_text = AsyncMock()

    with (
        patch(
            "app.api.webhooks.stripe._buscar_agronomo_por_customer",
            AsyncMock(return_value=agronomo),
        ),
        patch("app.api.webhooks.stripe._atualizar_status", AsyncMock()),
        patch("app.api.webhooks.stripe.whatsapp", mock_wpp),
    ):
        await _handle_payment_succeeded(event, mock_db)

    # Renovação normal → sem mensagem pro agrônomo
    mock_wpp.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_payment_succeeded_customer_nao_encontrado_nao_crasha():
    """Customer desconhecido → loga e retorna sem crash."""
    from app.api.webhooks.stripe import _handle_payment_succeeded

    mock_db = AsyncMock()
    event = MagicMock()
    event.data.object.get = lambda key, *a: "cus_desconhecido" if key == "customer" else None

    with patch(
        "app.api.webhooks.stripe._buscar_agronomo_por_customer",
        AsyncMock(return_value=None),
    ):
        await _handle_payment_succeeded(event, mock_db)  # não deve lançar


# ── _HANDLERS contém os 5 eventos ────────────────────────────────────────────


def test_cinco_eventos_registrados():
    from app.api.webhooks.stripe import _HANDLERS

    eventos_obrigatorios = {
        "customer.subscription.created",
        "customer.subscription.deleted",
        "invoice.payment_succeeded",
        "invoice.payment_failed",
        "customer.subscription.trial_will_end",
    }
    assert eventos_obrigatorios == set(_HANDLERS.keys())
