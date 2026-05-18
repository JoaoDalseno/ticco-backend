import pytest
from unittest.mock import AsyncMock, patch
from app.services.ai_processor import AIProcessor
from app.schemas.visita import VisitaDadosEstruturados

FAZENDAS_MOCK = [
    {
        "nome": "Fazenda Bela Vista",
        "cidade": "Pedregulho",
        "area_ha": 150.0,
        "talhoes": [
            {"nome": "Talhão 1", "area_ha": 50.0, "variedade": "catuai_vermelho_144"},
            {"nome": "Talhão 2", "area_ha": 60.0, "variedade": "bourbon_amarelo"},
            {"nome": "Talhão 3", "area_ha": 40.0, "variedade": "mundo_novo"},
        ],
    }
]

RELATO_MOCK = """
Visitei hoje a Bela Vista, fui no talhão 3.
Encontrei ferrugem com severidade média em uns 15 hectares.
Tem também broca no início, nível leve.
Recomendo aplicar Cuprozeb 2kg por hectare nos próximos 5 dias.
Próxima visita semana que vem, dia 25.
"""

JSON_MOCK = """{
    "fazenda_identificada": "Fazenda Bela Vista",
    "talhao_identificado": "Talhão 3",
    "estadio_fenologico": "granacao",
    "pragas_identificadas": [
        {
            "nome_popular": "broca",
            "nome_cientifico": "Hypothenemus hampei",
            "severidade": "leve",
            "area_afetada_ha": null
        }
    ],
    "doencas_identificadas": [
        {
            "nome": "ferrugem",
            "severidade": "media",
            "area_afetada_ha": 15.0
        }
    ],
    "recomendacoes": [
        {
            "produto_sugerido": "Cuprozeb",
            "ingrediente_ativo": "cobre + mancozebe",
            "dose": "2 kg/ha",
            "volume_calda": null,
            "area_ha": null,
            "prioridade": "alta",
            "justificativa": "Controle de ferrugem em estádio crítico",
            "periodo_carencia_dias": null,
            "epi": null
        }
    ],
    "observacoes_gerais": null,
    "proxima_visita_sugerida": "2026-05-25",
    "confianca_identificacao": "alta"
}"""


@pytest.mark.asyncio
async def test_extract_visita_data_sucesso():
    processor = AIProcessor()

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text=JSON_MOCK)]

    with patch.object(processor.client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        resultado = await processor.extract_visita_data(
            texto_bruto=RELATO_MOCK,
            fazendas_contexto=FAZENDAS_MOCK,
        )

    assert resultado.fazenda_identificada == "Fazenda Bela Vista"
    assert resultado.talhao_identificado == "Talhão 3"
    assert len(resultado.pragas_identificadas) == 1
    assert resultado.pragas_identificadas[0].nome_popular == "broca"
    assert len(resultado.doencas_identificadas) == 1
    assert resultado.doencas_identificadas[0].severidade == "media"
    assert len(resultado.recomendacoes) == 1
    assert resultado.confianca_identificacao == "alta"


@pytest.mark.asyncio
async def test_gerar_resumo_whatsapp():
    processor = AIProcessor()

    mock_response = AsyncMock()
    mock_response.content = [AsyncMock(text=JSON_MOCK)]

    with patch.object(processor.client.messages, "create", new_callable=AsyncMock, return_value=mock_response):
        dados = await processor.extract_visita_data(
            texto_bruto=RELATO_MOCK,
            fazendas_contexto=FAZENDAS_MOCK,
        )

    resumo = await processor.gerar_resumo_whatsapp(
        dados=dados,
        nome_agronomo="João Silva",
    )

    assert "Fazenda Bela Vista" in resumo
    assert "ferrugem" in resumo.lower()
    assert "broca" in resumo.lower()
    assert "Cuprozeb" in resumo


@pytest.mark.asyncio
async def test_extract_visita_data_retry_em_json_invalido():
    processor = AIProcessor()

    json_invalido = "isso não é json"
    mock_response_invalido = AsyncMock()
    mock_response_invalido.content = [AsyncMock(text=json_invalido)]

    mock_response_valido = AsyncMock()
    mock_response_valido.content = [AsyncMock(text=JSON_MOCK)]

    with patch.object(
        processor.client.messages,
        "create",
        new_callable=AsyncMock,
        side_effect=[mock_response_invalido, mock_response_valido],
    ):
        resultado = await processor.extract_visita_data(
            texto_bruto=RELATO_MOCK,
            fazendas_contexto=FAZENDAS_MOCK,
        )

    assert resultado.fazenda_identificada == "Fazenda Bela Vista"
    assert resultado.confianca_identificacao == "alta"
