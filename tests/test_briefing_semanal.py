"""
Testes para app/workers/briefing_semanal.py

Estratégia: mock de DB, whatsapp e anthropic — sem I/O real.
"""
import uuid
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.visita import StatusVisitaEnum


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fazenda(modulo_ativo=True, dono_wpp="+5516999990001", nome="Fazenda Teste"):
    f = MagicMock()
    f.id = uuid.uuid4()
    f.agronomo_id = uuid.uuid4()
    f.nome = nome
    f.dono_nome = "José Dono"
    f.dono_wpp = dono_wpp if modulo_ativo else None
    f.modulo_dono_ativo = modulo_ativo
    return f


def _agronomo(nome="Dr. Agrônomo"):
    a = MagicMock()
    a.id = uuid.uuid4()
    a.nome = nome
    return a


def _visita(data_visita=None, dados=None):
    v = MagicMock()
    v.id = uuid.uuid4()
    v.data_visita = data_visita or date.today() - timedelta(days=2)
    v.status = StatusVisitaEnum.completa
    v.dados_estruturados = dados or {
        "talhao_identificado": "Talhão Norte",
        "pragas_identificadas": [{"nome_popular": "Bicho-mineiro"}],
        "doencas_identificadas": [{"nome": "Ferrugem"}],
        "recomendacoes": [{"produto_sugerido": "Fungicida X"}],
        "observacoes_gerais": "Lavoura em bom estado geral.",
    }
    return v


# ── processar_briefing_fazenda — sem visitas ──────────────────────────────────


@pytest.mark.asyncio
async def test_sem_visitas_envia_mensagem_padrao():
    """Fazenda sem visitas na semana recebe mensagem estática."""
    from app.workers.briefing_semanal import processar_briefing_fazenda

    fazenda = _fazenda()
    agronomo = _agronomo("Maria Agrônoma")

    mock_db = AsyncMock()
    # db.execute retorna resultado sem visitas
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=exec_result)
    # db.get retorna o agrônomo
    mock_db.get = AsyncMock(return_value=agronomo)

    mock_wpp = AsyncMock()
    mock_wpp.send_text = AsyncMock()

    with patch("app.workers.briefing_semanal.whatsapp", mock_wpp):
        await processar_briefing_fazenda(fazenda, mock_db)

    mock_wpp.send_text.assert_awaited_once()
    destino, msg = mock_wpp.send_text.call_args.args
    assert destino == fazenda.dono_wpp
    assert "Nenhuma visita" in msg
    assert fazenda.nome in msg
    assert agronomo.nome in msg


@pytest.mark.asyncio
async def test_sem_visitas_agronomo_none_nao_crasha():
    """Se agrônomo não for encontrado no DB, ainda envia mensagem sem crash."""
    from app.workers.briefing_semanal import processar_briefing_fazenda

    fazenda = _fazenda()

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    mock_db.execute = AsyncMock(return_value=exec_result)
    mock_db.get = AsyncMock(return_value=None)  # agrônomo não encontrado

    mock_wpp = AsyncMock()
    mock_wpp.send_text = AsyncMock()

    with patch("app.workers.briefing_semanal.whatsapp", mock_wpp):
        await processar_briefing_fazenda(fazenda, mock_db)

    mock_wpp.send_text.assert_awaited_once()


# ── processar_briefing_fazenda — com visitas ──────────────────────────────────


@pytest.mark.asyncio
async def test_com_visitas_chama_claude_e_envia():
    """Fazenda com visitas gera resumo via Claude e envia ao dono."""
    from app.workers.briefing_semanal import processar_briefing_fazenda

    fazenda = _fazenda()
    agronomo = _agronomo()
    visitas = [_visita(), _visita()]

    mock_db = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = visitas
    mock_db.execute = AsyncMock(return_value=exec_result)
    mock_db.get = AsyncMock(return_value=agronomo)

    mock_wpp = AsyncMock()
    mock_wpp.send_text = AsyncMock()

    resumo_esperado = "Bom dia, José! Semana foi boa na fazenda. 🌱"

    with (
        patch("app.workers.briefing_semanal.whatsapp", mock_wpp),
        patch("app.workers.briefing_semanal.gerar_resumo_semanal", AsyncMock(return_value=resumo_esperado)),
    ):
        await processar_briefing_fazenda(fazenda, mock_db)

    mock_wpp.send_text.assert_awaited_once_with(fazenda.dono_wpp, resumo_esperado)


# ── gerar_resumo_semanal ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gerar_resumo_chama_claude_com_dados_corretos():
    """gerar_resumo_semanal monta prompt e chama anthropic.AsyncAnthropic."""
    from app.workers.briefing_semanal import gerar_resumo_semanal

    fazenda = _fazenda(nome="Fazenda São João")
    agronomo = _agronomo("Dr. Paulo")
    visitas = [_visita()]

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Resumo gerado pelo Claude.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.workers.briefing_semanal.anthropic.AsyncAnthropic", return_value=mock_client):
        resultado = await gerar_resumo_semanal(fazenda, visitas, agronomo)

    assert resultado == "Resumo gerado pelo Claude."
    mock_client.messages.create.assert_awaited_once()
    _, kwargs = mock_client.messages.create.call_args
    prompt = kwargs["messages"][0]["content"]
    assert fazenda.nome in prompt
    assert fazenda.dono_nome in prompt
    assert agronomo.nome in prompt
    assert "claude-haiku-4-5" == kwargs["model"]


@pytest.mark.asyncio
async def test_gerar_resumo_agronomo_none():
    """gerar_resumo_semanal funciona mesmo sem agrônomo."""
    from app.workers.briefing_semanal import gerar_resumo_semanal

    fazenda = _fazenda()
    visitas = [_visita()]

    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Ok.")]
    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    with patch("app.workers.briefing_semanal.anthropic.AsyncAnthropic", return_value=mock_client):
        resultado = await gerar_resumo_semanal(fazenda, visitas, agronomo=None)

    assert resultado == "Ok."


# ── enviar_briefings_semanais ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_enviar_briefings_processa_todas_fazendas():
    """enviar_briefings_semanais itera todas as fazendas com módulo ativo."""
    from app.workers.briefing_semanal import enviar_briefings_semanais

    fazendas = [_fazenda(nome="F1"), _fazenda(nome="F2")]

    mock_db_ctx = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = fazendas
    mock_db_ctx.execute = AsyncMock(return_value=exec_result)
    mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db_ctx)
    mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

    processar_mock = AsyncMock()

    with (
        patch("app.workers.briefing_semanal.AsyncSessionLocal", return_value=mock_db_ctx),
        patch("app.workers.briefing_semanal.processar_briefing_fazenda", processar_mock),
        patch("asyncio.sleep", AsyncMock()),  # não aguarda o delay real
    ):
        await enviar_briefings_semanais()

    assert processar_mock.await_count == 2


@pytest.mark.asyncio
async def test_enviar_briefings_erro_em_uma_fazenda_nao_para_outras():
    """Erro em uma fazenda não impede o envio para as demais."""
    from app.workers.briefing_semanal import enviar_briefings_semanais

    fazendas = [_fazenda(nome="OK"), _fazenda(nome="Falha"), _fazenda(nome="OK2")]

    mock_db_ctx = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = fazendas
    mock_db_ctx.execute = AsyncMock(return_value=exec_result)
    mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db_ctx)
    mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

    call_count = 0

    async def processar_side_effect(fazenda, db):
        nonlocal call_count
        call_count += 1
        if fazenda.nome == "Falha":
            raise RuntimeError("Z-API timeout")

    with (
        patch("app.workers.briefing_semanal.AsyncSessionLocal", return_value=mock_db_ctx),
        patch("app.workers.briefing_semanal.processar_briefing_fazenda", side_effect=processar_side_effect),
        patch("asyncio.sleep", AsyncMock()),
    ):
        await enviar_briefings_semanais()

    # Todas as 3 fazendas tentadas, apesar do erro na segunda
    assert call_count == 3


@pytest.mark.asyncio
async def test_delay_entre_envios():
    """Confirma que asyncio.sleep(2) é chamado entre fazendas."""
    from app.workers.briefing_semanal import enviar_briefings_semanais

    fazendas = [_fazenda(nome="F1"), _fazenda(nome="F2")]

    mock_db_ctx = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = fazendas
    mock_db_ctx.execute = AsyncMock(return_value=exec_result)
    mock_db_ctx.__aenter__ = AsyncMock(return_value=mock_db_ctx)
    mock_db_ctx.__aexit__ = AsyncMock(return_value=False)

    sleep_mock = AsyncMock()

    with (
        patch("app.workers.briefing_semanal.AsyncSessionLocal", return_value=mock_db_ctx),
        patch("app.workers.briefing_semanal.processar_briefing_fazenda", AsyncMock()),
        patch("app.workers.briefing_semanal.asyncio.sleep", sleep_mock),
    ):
        await enviar_briefings_semanais()

    # 2 fazendas → 2 sleeps de 2 segundos
    assert sleep_mock.await_count == 2
    sleep_mock.assert_awaited_with(2)
