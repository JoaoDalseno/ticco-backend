"""
Testes do serviço de onboarding conversacional.
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.onboarding import (
    MSGS,
    OnboardingService,
    formatar_cpf,
    handle_onboarding_step,
    validar_cpf,
    validar_crea,
)

PHONE = "+5516999990001"
CPF_VALIDO = "12345678901"
CREA_VALIDO = "SP-123456/D"
CIDADE_VALIDA = "Pedregulho"
NOME_VALIDO = "João Silva"


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def svc():
    return OnboardingService()


@pytest.fixture
def whatsapp_mock():
    mock = MagicMock()
    mock.send_text = AsyncMock()
    return mock


@pytest.fixture
def db_mock():
    mock = MagicMock()
    mock.add = MagicMock()
    mock.commit = AsyncMock()
    mock.refresh = AsyncMock()
    return mock


# ── Validações ────────────────────────────────────────────────────────────────

def test_validar_crea_aceita_formato_padrao():
    assert validar_crea("SP-123456/D") is True


def test_validar_crea_aceita_variacao():
    assert validar_crea("MG-98765/D") is True


def test_validar_crea_rejeita_muito_curto():
    assert validar_crea("AB1") is False


def test_validar_cpf_aceita_11_digitos():
    assert validar_cpf("12345678901") is True


def test_validar_cpf_aceita_com_formatacao():
    assert validar_cpf("123.456.789-01") is True


def test_validar_cpf_rejeita_menos_de_11():
    assert validar_cpf("1234567890") is False


def test_validar_cpf_rejeita_mais_de_11():
    assert validar_cpf("123456789012") is False


def test_formatar_cpf():
    assert formatar_cpf("12345678901") == "123.456.789-01"
    assert formatar_cpf("123.456.789-01") == "123.456.789-01"


# ── OnboardingService ─────────────────────────────────────────────────────────

def test_start_onboarding_cria_sessao(svc):
    svc.start_onboarding(PHONE)
    assert svc.is_in_onboarding(PHONE) is True
    assert svc.get_step(PHONE) == "aguarda_confirmacao"


def test_is_in_onboarding_false_sem_sessao(svc):
    assert svc.is_in_onboarding(PHONE) is False


def test_get_step_none_sem_sessao(svc):
    assert svc.get_step(PHONE) is None


def test_set_dado_e_get_dados(svc):
    svc.start_onboarding(PHONE)
    svc.set_dado(PHONE, "nome", "João Silva")
    assert svc.get_dados(PHONE)["nome"] == "João Silva"


def test_advance_step_sequencia(svc):
    svc.start_onboarding(PHONE)
    assert svc.get_step(PHONE) == "aguarda_confirmacao"

    svc.advance_step(PHONE)
    assert svc.get_step(PHONE) == "aguarda_nome"

    svc.advance_step(PHONE)
    assert svc.get_step(PHONE) == "aguarda_crea"

    svc.advance_step(PHONE)
    assert svc.get_step(PHONE) == "aguarda_cidade"

    svc.advance_step(PHONE)
    assert svc.get_step(PHONE) == "aguarda_cpf"

    svc.advance_step(PHONE)
    assert svc.get_step(PHONE) == "concluido"


def test_clear_session_remove_sessao(svc):
    svc.start_onboarding(PHONE)
    svc.clear_session(PHONE)
    assert svc.is_in_onboarding(PHONE) is False


def test_sessao_expirada_removida(svc):
    svc.start_onboarding(PHONE)
    # Força expiração retroagindo o expires_at
    svc._sessions[PHONE]["expires_at"] = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert svc.is_in_onboarding(PHONE) is False


# ── handle_onboarding_step ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step_confirmacao_sim(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    await handle_onboarding_step(PHONE, "sim", db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_nome"
    whatsapp_mock.send_text.assert_called_once_with(PHONE, MSGS["pede_nome"])


@pytest.mark.asyncio
async def test_step_confirmacao_nao(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    await handle_onboarding_step(PHONE, "não", db_mock, whatsapp_mock, svc)

    assert svc.is_in_onboarding(PHONE) is False
    whatsapp_mock.send_text.assert_called_once_with(PHONE, MSGS["cancelado"])


@pytest.mark.asyncio
async def test_step_confirmacao_nao_entendi(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    await handle_onboarding_step(PHONE, "talvez", db_mock, whatsapp_mock, svc)

    # Não deve avançar nem encerrar
    assert svc.get_step(PHONE) == "aguarda_confirmacao"
    whatsapp_mock.send_text.assert_called_once_with(PHONE, MSGS["nao_entendi"])


@pytest.mark.asyncio
async def test_step_nome_valido(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # → aguarda_nome
    await handle_onboarding_step(PHONE, NOME_VALIDO, db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_crea"
    assert svc.get_dados(PHONE)["nome"] == NOME_VALIDO.title()
    whatsapp_mock.send_text.assert_called_once_with(PHONE, MSGS["pede_crea"])


@pytest.mark.asyncio
async def test_step_nome_muito_curto(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # → aguarda_nome
    await handle_onboarding_step(PHONE, "Jo", db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_nome"  # não avançou


@pytest.mark.asyncio
async def test_step_crea_valido(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # nome
    svc.advance_step(PHONE)  # crea
    await handle_onboarding_step(PHONE, CREA_VALIDO, db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_cidade"
    assert svc.get_dados(PHONE)["crea"] == CREA_VALIDO.upper()


@pytest.mark.asyncio
async def test_step_crea_invalido(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # nome
    svc.advance_step(PHONE)  # crea
    await handle_onboarding_step(PHONE, "AB1", db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_crea"  # não avançou


@pytest.mark.asyncio
async def test_step_cidade_valida(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # nome
    svc.advance_step(PHONE)  # crea
    svc.advance_step(PHONE)  # cidade
    await handle_onboarding_step(PHONE, CIDADE_VALIDA, db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_cpf"
    assert svc.get_dados(PHONE)["cidade"] == CIDADE_VALIDA.title()


@pytest.mark.asyncio
async def test_step_cpf_invalido_nao_avanca(svc, whatsapp_mock, db_mock):
    svc.start_onboarding(PHONE)
    # Avança até aguarda_cpf e preenche dados anteriores
    svc.advance_step(PHONE)  # nome
    svc.set_dado(PHONE, "nome", "João Silva")
    svc.advance_step(PHONE)  # crea
    svc.set_dado(PHONE, "crea", "SP-123456/D")
    svc.advance_step(PHONE)  # cidade
    svc.set_dado(PHONE, "cidade", "Pedregulho")
    svc.advance_step(PHONE)  # cpf

    await handle_onboarding_step(PHONE, "123", db_mock, whatsapp_mock, svc)

    assert svc.get_step(PHONE) == "aguarda_cpf"  # não avançou
    assert svc.is_in_onboarding(PHONE) is True


@pytest.mark.asyncio
async def test_fluxo_completo_cria_agronomo(svc, whatsapp_mock, db_mock):
    """Simula o fluxo completo do onboarding do início ao fim."""
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)  # nome
    svc.set_dado(PHONE, "nome", "João Silva")
    svc.advance_step(PHONE)  # crea
    svc.set_dado(PHONE, "crea", "SP-123456/D")
    svc.advance_step(PHONE)  # cidade
    svc.set_dado(PHONE, "cidade", "Pedregulho")
    svc.advance_step(PHONE)  # cpf

    with patch("app.services.onboarding._criar_agronomo_via_onboarding", new_callable=AsyncMock) as mock_criar, \
         patch("app.services.onboarding.settings") as mock_settings:
        mock_settings.founder_phone = ""
        await handle_onboarding_step(PHONE, CPF_VALIDO, db_mock, whatsapp_mock, svc)

    # Deve ter chamado a criação
    mock_criar.assert_called_once()
    call_kwargs = mock_criar.call_args.kwargs
    assert call_kwargs["phone"] == PHONE
    assert call_kwargs["dados"]["cpf"] == formatar_cpf(CPF_VALIDO)

    # Sessão deve ter sido limpa
    assert svc.is_in_onboarding(PHONE) is False

    # Mensagem de conclusão enviada
    msg_enviada = whatsapp_mock.send_text.call_args[0][1]
    assert "João Silva" in msg_enviada
    assert "14 dias" in msg_enviada


@pytest.mark.asyncio
async def test_notifica_fundador_ao_concluir(svc, whatsapp_mock, db_mock):
    """Verifica que o fundador recebe notificação quando FOUNDER_PHONE está configurado."""
    svc.start_onboarding(PHONE)
    svc.advance_step(PHONE)
    svc.set_dado(PHONE, "nome", "Maria Souza")
    svc.advance_step(PHONE)
    svc.set_dado(PHONE, "crea", "MG-999999/D")
    svc.advance_step(PHONE)
    svc.set_dado(PHONE, "cidade", "Patrocínio")
    svc.advance_step(PHONE)

    FOUNDER = "+5516900000000"

    with patch("app.services.onboarding._criar_agronomo_via_onboarding", new_callable=AsyncMock), \
         patch("app.services.onboarding.settings") as mock_settings:
        mock_settings.founder_phone = FOUNDER
        await handle_onboarding_step(PHONE, CPF_VALIDO, db_mock, whatsapp_mock, svc)

    # Duas mensagens enviadas: boas-vindas pro agrônomo + notificação pro fundador
    assert whatsapp_mock.send_text.call_count == 2
    calls = whatsapp_mock.send_text.call_args_list
    phones_destino = [c[0][0] for c in calls]
    assert FOUNDER in phones_destino
