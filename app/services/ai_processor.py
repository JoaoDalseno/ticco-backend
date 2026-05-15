"""
Pipeline de IA — Claude claude-sonnet-4-5 estrutura o relato de visita técnica.

Usa tool_use para garantir JSON válido com o schema VisitaDadosEstruturados.
"""
import logging

import anthropic

from app.config import settings
from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.talhao import Talhao
from app.schemas.visita import VisitaDadosEstruturados

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

# ── Tool schema (espelha VisitaDadosEstruturados) ────────────────────────────

_TOOL: dict = {
    "name": "estruturar_visita",
    "description": (
        "Registra os dados estruturados extraídos do relato de visita técnica cafeicultora."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "fazenda_identificada": {
                "type": ["string", "null"],
                "description": "Nome da fazenda mencionada no relato.",
            },
            "talhao_identificado": {
                "type": ["string", "null"],
                "description": "Nome ou identificação do talhão visitado.",
            },
            "confianca_identificacao": {
                "type": "string",
                "enum": ["alta", "media", "baixa"],
                "description": "Confiança na identificação de fazenda/talhão.",
            },
            "data_visita": {
                "type": ["string", "null"],
                "description": "Data da visita em formato ISO (YYYY-MM-DD). Use hoje se não mencionado.",
            },
            "estadio_fenologico": {
                "type": ["string", "null"],
                "description": "Estádio fenológico do café (ex: florada, granação, cereja).",
            },
            "pragas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                        "severidade": {"type": "string", "enum": ["leve", "media", "alta"]},
                        "area_afetada_pct": {"type": ["number", "null"]},
                        "observacao": {"type": ["string", "null"]},
                    },
                    "required": ["nome", "severidade"],
                },
            },
            "doencas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string"},
                        "severidade": {"type": "string", "enum": ["leve", "media", "alta"]},
                        "area_afetada_pct": {"type": ["number", "null"]},
                        "observacao": {"type": ["string", "null"]},
                    },
                    "required": ["nome", "severidade"],
                },
            },
            "recomendacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "tipo": {"type": "string"},
                        "descricao": {"type": "string"},
                        "produto": {"type": ["string", "null"]},
                        "dose": {"type": ["string", "null"]},
                        "area_ha": {"type": ["number", "null"]},
                        "justificativa": {"type": ["string", "null"]},
                    },
                    "required": ["tipo", "descricao"],
                },
            },
            "produtos_receituario": {
                "type": "array",
                "description": "Produtos que exigem receituário agronômico.",
                "items": {
                    "type": "object",
                    "properties": {
                        "nome_comercial": {"type": "string"},
                        "ingrediente_ativo": {"type": "string"},
                        "cultura": {"type": "string"},
                        "praga_alvo": {"type": "string"},
                        "dose": {"type": "string"},
                        "volume_calda": {"type": ["string", "null"]},
                        "epoca_aplicacao": {"type": ["string", "null"]},
                        "intervalo_seguranca_dias": {"type": ["integer", "null"]},
                        "epis": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["nome_comercial", "ingrediente_ativo", "cultura", "praga_alvo", "dose"],
                },
            },
            "observacoes_gerais": {
                "type": ["string", "null"],
                "description": "Observações gerais não categorizadas.",
            },
            "proxima_visita": {
                "type": ["string", "null"],
                "description": "Data sugerida para próxima visita (ISO YYYY-MM-DD).",
            },
        },
        "required": [
            "confianca_identificacao",
            "pragas",
            "doencas",
            "recomendacoes",
            "produtos_receituario",
        ],
    },
}


def _contexto_agronomo(agronomo: Agronomo, fazendas: list[Fazenda]) -> str:
    """Monta o contexto com fazendas e talhões do agrônomo para o system prompt."""
    linhas = [f"Agrônomo: {agronomo.nome} (CREA: {agronomo.crea})", "", "Fazendas cadastradas:"]
    for f in fazendas:
        linhas.append(f"  • {f.nome} — dono: {f.dono_nome} — {f.cidade}/{f.estado} ({f.area_total_ha} ha)")
        for t in f.talhoes:
            info = f"    – {t.nome} ({t.area_ha} ha"
            if t.variedade:
                info += f", variedade: {t.variedade}"
            if t.ano_plantio:
                info += f", plantio: {t.ano_plantio}"
            info += ")"
            linhas.append(info)
    return "\n".join(linhas)


def _system_prompt(agronomo: Agronomo, fazendas: list[Fazenda]) -> str:
    contexto = _contexto_agronomo(agronomo, fazendas)
    return f"""Você é um assistente especializado em agronomia cafeicultora brasileira.
Sua tarefa é analisar relatos de visitas técnicas e extrair dados estruturados.

{contexto}

Instruções:
- Identifique a fazenda e o talhão mencionados comparando com as fazendas cadastradas acima.
- Extraia todas as pragas, doenças, recomendações e produtos mencionados.
- Para produtos fitossanitários (fungicidas, inseticidas, herbicidas), preencha produtos_receituario.
- Use o campo confianca_identificacao para indicar seu nível de certeza na identificação de fazenda/talhão.
- Sempre use a ferramenta estruturar_visita para retornar os dados."""


async def processar_relato(
    texto: str,
    agronomo: Agronomo,
    fazendas: list[Fazenda],
) -> VisitaDadosEstruturados:
    """
    Envia o texto do relato para o Claude e retorna os dados estruturados.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    logger.info("Enviando relato ao Claude — %d chars", len(texto))

    response = await client.messages.create(
        model=_MODEL,
        max_tokens=2048,
        system=_system_prompt(agronomo, fazendas),
        tools=[_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": texto}],
    )

    # Extrai o tool_use block
    tool_block = next(
        (b for b in response.content if b.type == "tool_use" and b.name == "estruturar_visita"),
        None,
    )
    if not tool_block:
        logger.error("Claude não retornou tool_use. Stop reason: %s", response.stop_reason)
        raise ValueError("Claude não retornou dados estruturados")

    dados = tool_block.input
    logger.info("Claude estruturou visita — fazenda=%s talhão=%s confiança=%s",
                dados.get("fazenda_identificada"), dados.get("talhao_identificado"),
                dados.get("confianca_identificacao"))

    return VisitaDadosEstruturados(**dados)
