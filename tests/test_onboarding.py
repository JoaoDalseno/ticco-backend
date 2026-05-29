"""Testes do onboarding via WhatsApp (app/services/whatsapp/onboarding.py)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.whatsapp import onboarding as ob

PHONE = "+5516999990001"


@pytest.fixture(autouse=True)
def _reset_estados():
    ob._estados.clear()
    yield
    ob._estados.clear()


@pytest.fixture
def db_mock():
    mock = MagicMock()
    mock.add = MagicMock()
    mock.commit = AsyncMock()
    mock.rollback = AsyncMock()
    return mock


# ── Validação de CPF ──────────────────────────────────────────────────────────

def test_cpf_valido_aceita_cpf_correto():
    # 529.982.247-25 — CPF válido público de exemplo
    assert ob._cpf_valido("52998224725") is True
    assert ob._cpf_valido("529.982.247-25") is True


def test_cpf_invalido_rejeita_digitos_repetidos():
    assert ob._cpf_valido("11111111111") is False


def test_cpf_invalido_rejeita_tamanho_errado():
    assert ob._cpf_valido("123") is False
    assert ob._cpf_valido("123456789012") is False


def test_cpf_invalido_rejeita_digito_verificador_errado():
    assert ob._cpf_valido("12345678900") is False


def test_crea_valido():
    assert ob._crea_valido("SP-123456/D") is True
    assert ob._crea_valido("AB12") is True


def test_crea_invalido_muito_curto():
    assert ob._crea_valido("AB1") is False


# ── Fluxo de onboarding ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_iniciar_envia_boas_vindas_e_seta_estado():
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock) as mock_send:
        await ob.iniciar(PHONE)

    assert ob.em_onboarding(PHONE) is True
    assert ob._estados[PHONE]["etapa"] == ob.Etapa.NOME
    mock_send.assert_called_once_with(PHONE, ob.BOAS_VINDAS)


@pytest.mark.asyncio
async def test_processar_resposta_sem_sessao_inicia_onboarding(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock) as mock_send:
        await ob.processar_resposta(PHONE, "qualquer", db_mock)

    assert ob.em_onboarding(PHONE) is True
    mock_send.assert_called_once_with(PHONE, ob.BOAS_VINDAS)


@pytest.mark.asyncio
async def test_etapa_nome_avanca_pra_cpf(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock):
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)

    assert ob._estados[PHONE]["etapa"] == ob.Etapa.CPF
    assert ob._estados[PHONE]["dados"]["nome"] == "João Silva"


@pytest.mark.asyncio
async def test_etapa_nome_rejeita_muito_curto(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock):
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "Jo", db_mock)

    assert ob._estados[PHONE]["etapa"] == ob.Etapa.NOME


@pytest.mark.asyncio
async def test_etapa_cpf_avanca_com_cpf_valido(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock):
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)
        await ob.processar_resposta(PHONE, "529.982.247-25", db_mock)

    assert ob._estados[PHONE]["etapa"] == ob.Etapa.CREA
    assert ob._estados[PHONE]["dados"]["cpf"] == "52998224725"


@pytest.mark.asyncio
async def test_etapa_cpf_rejeita_invalido(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock):
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)
        await ob.processar_resposta(PHONE, "11111111111", db_mock)

    assert ob._estados[PHONE]["etapa"] == ob.Etapa.CPF


@pytest.mark.asyncio
async def test_etapa_crea_avanca_pra_email(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock):
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)
        await ob.processar_resposta(PHONE, "52998224725", db_mock)
        await ob.processar_resposta(PHONE, "SP-123456/D", db_mock)

    assert ob._estados[PHONE]["etapa"] == ob.Etapa.EMAIL
    assert ob._estados[PHONE]["dados"]["crea"] == "SP-123456/D"


@pytest.mark.asyncio
async def test_fluxo_completo_cria_agronomo(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock), \
         patch("app.services.whatsapp.onboarding._criar_agronomo", new_callable=AsyncMock) as mock_criar:
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)
        await ob.processar_resposta(PHONE, "52998224725", db_mock)
        await ob.processar_resposta(PHONE, "SP-123456/D", db_mock)
        await ob.processar_resposta(PHONE, "joao@example.com", db_mock)

    mock_criar.assert_called_once()
    args, _ = mock_criar.call_args
    assert args[0] == PHONE
    assert args[1]["nome"] == "João Silva"
    assert args[1]["cpf"] == "52998224725"
    assert args[1]["crea"] == "SP-123456/D"
    assert args[1]["email"] == "joao@example.com"
    assert ob.em_onboarding(PHONE) is False


@pytest.mark.asyncio
async def test_email_pular_grava_none(db_mock):
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock), \
         patch("app.services.whatsapp.onboarding._criar_agronomo", new_callable=AsyncMock) as mock_criar:
        await ob.iniciar(PHONE)
        await ob.processar_resposta(PHONE, "João Silva", db_mock)
        await ob.processar_resposta(PHONE, "52998224725", db_mock)
        await ob.processar_resposta(PHONE, "SP-123456/D", db_mock)
        await ob.processar_resposta(PHONE, "pular", db_mock)

    assert mock_criar.call_args[0][1]["email"] is None


@pytest.mark.asyncio
async def test_audio_em_onboarding_pede_texto(db_mock):
    """Quando usuário em onboarding manda áudio (texto vazio), recebe orientação."""
    with patch("app.services.whatsapp.onboarding.whatsapp_module.send_text", new_callable=AsyncMock) as mock_send:
        await ob.iniciar(PHONE)
        mock_send.reset_mock()
        await ob.processar_resposta(PHONE, "", db_mock)

    assert mock_send.called
    msg = mock_send.call_args[0][1]
    assert "texto" in msg.lower() or "escreva" in msg.lower()
