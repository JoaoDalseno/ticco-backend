"""
Worker de briefing semanal — envia resumo das visitas da semana
para o dono de cada fazenda com modulo_dono_ativo=True.

Rodar toda segunda às 8h (Brasília) = 11h UTC.
Cron Railway: `0 11 * * 1`

Uso local:
    python -m app.workers.briefing_semanal
"""
import asyncio
from datetime import date, timedelta

import anthropic
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.visita import StatusVisitaEnum, Visita
from app.services.whatsapp.zapi import ZAPIWhatsAppService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
whatsapp = ZAPIWhatsAppService()


# ── Entry-point principal ─────────────────────────────────────────────────────

async def enviar_briefings_semanais() -> None:
    """
    Envia briefing semanal pra todos os donos
    com modulo_dono_ativo=True.
    Rodar toda segunda às 8h (Brasília).
    """
    logger.info("Iniciando envio de briefings semanais...")
    total_enviados = 0
    total_erros = 0

    async with AsyncSessionLocal() as db:
        # Busca fazendas com módulo dono ativo e telefone configurado
        result = await db.execute(
            select(Fazenda).where(
                Fazenda.modulo_dono_ativo == True,  # noqa: E712
                Fazenda.dono_wpp != None,           # noqa: E711
            )
        )
        fazendas = result.scalars().all()

        logger.info("%d fazenda(s) com módulo dono ativo", len(fazendas))

        for fazenda in fazendas:
            try:
                await processar_briefing_fazenda(fazenda, db)
                total_enviados += 1
                # Delay entre envios pra não sobrecarregar Z-API
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(
                    "Erro no briefing da fazenda %s: %s", fazenda.nome, e, exc_info=True
                )
                total_erros += 1

    logger.info(
        "Briefings: %d enviados, %d erros", total_enviados, total_erros
    )


# ── Processamento por fazenda ─────────────────────────────────────────────────

async def processar_briefing_fazenda(fazenda: Fazenda, db) -> None:
    """Gera e envia briefing de uma fazenda."""

    # Busca visitas da última semana
    uma_semana_atras = date.today() - timedelta(days=7)

    result = await db.execute(
        select(Visita)
        .where(
            Visita.fazenda_id == fazenda.id,
            Visita.data_visita >= uma_semana_atras,
            Visita.status == StatusVisitaEnum.completa,
        )
        .order_by(Visita.data_visita.desc())
    )
    visitas = result.scalars().all()

    # Busca agrônomo responsável pela fazenda
    agronomo = await db.get(Agronomo, fazenda.agronomo_id)

    if not visitas:
        # Sem visitas na semana — mensagem padrão
        agronomo_nome = agronomo.nome if agronomo else "o agrônomo responsável"
        msg = (
            f"Bom dia! 🌱\n\n"
            f"*Resumo semanal — {fazenda.nome}*\n\n"
            f"Nenhuma visita técnica registrada essa semana.\n\n"
            f"_Seu agrônomo: {agronomo_nome}_\n\n"
            f"_Dúvidas? {settings.contact_email}_"
        )
        await whatsapp.send_text(fazenda.dono_wpp, msg)
        logger.info(
            "Briefing 'sem visitas' enviado — fazenda=%s dono=%s",
            fazenda.nome, fazenda.dono_nome,
        )
        return

    # Tem visitas — gera resumo com Claude
    resumo = await gerar_resumo_semanal(
        fazenda=fazenda,
        visitas=list(visitas),
        agronomo=agronomo,
    )

    resumo += f"\n\n_Dúvidas? {settings.contact_email}_"
    await whatsapp.send_text(fazenda.dono_wpp, resumo)
    logger.info(
        "Briefing enviado — fazenda=%s dono=%s visitas=%d",
        fazenda.nome, fazenda.dono_nome, len(visitas),
    )


# ── Geração de resumo via Claude ──────────────────────────────────────────────

async def gerar_resumo_semanal(
    fazenda: Fazenda,
    visitas: list[Visita],
    agronomo: Agronomo | None,
) -> str:
    """
    Gera resumo semanal via Claude Haiku.
    Tom: simples, direto, pra leigo (não agrônomo).
    """
    # Monta contexto das visitas para o prompt
    visitas_texto = ""
    for v in visitas:
        dados = v.dados_estruturados or {}
        pragas = dados.get("pragas_identificadas", [])
        doencas = dados.get("doencas_identificadas", [])
        recs = dados.get("recomendacoes", [])

        visitas_texto += (
            f"Data: {v.data_visita}\n"
            f"Talhão: {dados.get('talhao_identificado', 'não informado')}\n"
            f"Pragas: {[p['nome_popular'] for p in pragas]}\n"
            f"Doenças: {[d['nome'] for d in doencas]}\n"
            f"Recomendações: {[r['produto_sugerido'] for r in recs]}\n"
            f"Observações: {dados.get('observacoes_gerais', '')}\n\n"
        )

    agronomo_nome = agronomo.nome if agronomo else "Agrônomo não informado"
    data_inicio = date.today() - timedelta(days=7)

    client = anthropic.AsyncAnthropic()
    response = await client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=500,
        messages=[{
            "role": "user",
            "content": (
                f"Gera um resumo semanal CURTO e SIMPLES\n"
                f"da fazenda {fazenda.nome} pra o dono {fazenda.dono_nome}.\n\n"
                f"O dono NÃO é agrônomo — usa linguagem simples,\n"
                f"sem termos técnicos. Máximo 10 linhas.\n\n"
                f"Formato WhatsApp (usa *negrito* pra títulos):\n\n"
                f"Bom dia, [nome_curto]! 🌱\n\n"
                f"*Resumo semanal — [nome_fazenda]*\n"
                f"Semana de [data_inicio] a [data_fim]\n\n"
                f"[resumo das visitas em linguagem simples]\n\n"
                f"*Próximos passos:*\n"
                f"[o que vai acontecer de importante]\n\n"
                f"_Agrônomo responsável: [nome_agronomo]_\n\n"
                f"VISITAS DA SEMANA:\n"
                f"{visitas_texto}\n"
                f"Data atual: {date.today()}\n"
                f"Semana de: {data_inicio}\n"
                f"Nome do dono: {fazenda.dono_nome}\n"
                f"Nome da fazenda: {fazenda.nome}\n"
                f"Agrônomo: {agronomo_nome}"
            ),
        }],
    )

    return response.content[0].text


# ── Entry-point CLI ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    asyncio.run(enviar_briefings_semanais())
