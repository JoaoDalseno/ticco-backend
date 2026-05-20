"""
Testes para app/services/notificacao_fundador.py
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_whatsapp() -> AsyncMock:
    """Retorna um mock do ZAPIWhatsAppService com send_text async."""
    mock = AsyncMock()
    mock.send_text = AsyncMock()
    return mock


def _make_notificador(whatsapp, founder_phone: str = "+5516999990001"):
    """Instancia NotificacaoFundador com settings mockado."""
    from app.services.notificacao_fundador import NotificacaoFundador

    with patch("app.services.notificacao_fundador.settings") as mock_settings:
        mock_settings.founder_phone = founder_phone
        notificador = NotificacaoFundador(whatsapp)
        # Garante que o founder_phone já foi copiado no __init__
        notificador.founder_phone = founder_phone
    return notificador


# ── erro_pipeline ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_erro_pipeline_envia_mensagem():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp)

    await notificador.erro_pipeline(
        agronomo_nome="José Silva",
        agronomo_phone="+5516999990001",
        erro="TimeoutError ao chamar Claude",
        mensagem_id="abc-123",
    )

    whatsapp.send_text.assert_awaited_once()
    _, texto = whatsapp.send_text.call_args.args
    assert "🚨" in texto
    assert "José Silva" in texto
    assert "abc-123" in texto
    assert "TimeoutError" in texto


@pytest.mark.asyncio
async def test_erro_pipeline_trunca_erro_longo():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp)

    erro_longo = "X" * 500

    await notificador.erro_pipeline(
        agronomo_nome="João",
        agronomo_phone="+5516999990001",
        erro=erro_longo,
        mensagem_id="x",
    )

    _, texto = whatsapp.send_text.call_args.args
    # Apenas os primeiros 200 chars do erro devem aparecer
    assert "X" * 200 in texto
    assert "X" * 201 not in texto


@pytest.mark.asyncio
async def test_erro_pipeline_sem_founder_phone_nao_envia():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp, founder_phone="")

    await notificador.erro_pipeline(
        agronomo_nome="Teste",
        agronomo_phone="+5511000000000",
        erro="erro qualquer",
        mensagem_id="id",
    )

    whatsapp.send_text.assert_not_awaited()


# ── novo_cadastro ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_novo_cadastro_envia_mensagem():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp)

    await notificador.novo_cadastro(
        nome="Maria Oliveira",
        crea="SP-654321/D",
        cidade="Ribeirão Preto",
        phone="+5516988887777",
    )

    whatsapp.send_text.assert_awaited_once()
    _, texto = whatsapp.send_text.call_args.args
    assert "🐦" in texto
    assert "Maria Oliveira" in texto
    assert "SP-654321/D" in texto
    assert "Ribeirão Preto" in texto


@pytest.mark.asyncio
async def test_novo_cadastro_sem_founder_phone_nao_envia():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp, founder_phone="")

    await notificador.novo_cadastro(
        nome="Teste", crea="MG-001", cidade="BH", phone="+5531999990001"
    )

    whatsapp.send_text.assert_not_awaited()


# ── novo_pagamento ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_novo_pagamento_envia_mensagem():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp)

    await notificador.novo_pagamento(nome="Carlos", plano="basico", valor=199.0)

    whatsapp.send_text.assert_awaited_once()
    _, texto = whatsapp.send_text.call_args.args
    assert "💰" in texto
    assert "Carlos" in texto
    assert "basico" in texto
    assert "199.00" in texto


@pytest.mark.asyncio
async def test_novo_pagamento_sem_founder_phone_nao_envia():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp, founder_phone="")

    await notificador.novo_pagamento(nome="X", plano="completo", valor=349.0)

    whatsapp.send_text.assert_not_awaited()


# ── trial_expirado ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trial_expirado_envia_mensagem():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp)

    await notificador.trial_expirado(
        nome="Pedro Costa",
        phone="+5516977776666",
        dias_sem_pagar=17,
    )

    whatsapp.send_text.assert_awaited_once()
    _, texto = whatsapp.send_text.call_args.args
    assert "⏰" in texto
    assert "Pedro Costa" in texto
    assert "17" in texto


@pytest.mark.asyncio
async def test_trial_expirado_sem_founder_phone_nao_envia():
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp, founder_phone="")

    await notificador.trial_expirado(nome="X", phone="+5511000000000", dias_sem_pagar=5)

    whatsapp.send_text.assert_not_awaited()


# ── _enviar — erro silencioso ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enviar_erro_nao_propaga():
    """Erro no whatsapp.send_text não deve propagar para o chamador."""
    whatsapp = _make_whatsapp()
    whatsapp.send_text.side_effect = RuntimeError("Z-API indisponível")
    notificador = _make_notificador(whatsapp)

    # Não deve lançar exceção
    await notificador.erro_pipeline(
        agronomo_nome="Ana",
        agronomo_phone="+5516999990001",
        erro="erro qualquer",
        mensagem_id="id",
    )
    # send_text foi chamado (e falhou silenciosamente)
    whatsapp.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_enviar_destino_e_founder_phone():
    """A mensagem deve ser enviada para o FOUNDER_PHONE, não para o agrônomo."""
    founder = "+5516111112222"
    whatsapp = _make_whatsapp()
    notificador = _make_notificador(whatsapp, founder_phone=founder)

    await notificador.novo_pagamento(nome="Cliente", plano="completo", valor=349.0)

    destino, _ = whatsapp.send_text.call_args.args
    assert destino == founder
