"""
Script de seed — popula o banco com dados de teste.

Uso:
    python seed.py

Requer .env configurado com DATABASE_URL válido.
"""
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.agronomo import Agronomo, PlanoEnum, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.talhao import Talhao
from app.models.visita import Visita, StatusVisitaEnum
from app.models.mensagem import Mensagem, DirecaoEnum, TipoEnum

logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


async def seed() -> None:
    db_url = settings.database_url
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(db_url, echo=False)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        # ── Agrônomo de teste ────────────────────────────────────────────────
        agronomo = Agronomo(
            nome="Pedro Alves",
            cpf="12345678901",
            crea="SP-123456/D",
            telefone_wpp="+5516999998888",
            email="pedro@agrotecnica.com.br",
            plano=PlanoEnum.completo,
            status_pagamento=StatusPagamentoEnum.active,
            trial_ate=datetime.now(timezone.utc) + timedelta(days=14),
        )
        db.add(agronomo)
        await db.flush()
        logger.info("Agrônomo criado: %s — ID: %s", agronomo.nome, agronomo.id)

        # ── Fazenda 1 ────────────────────────────────────────────────────────
        fazenda1 = Fazenda(
            agronomo_id=agronomo.id,
            nome="Fazenda Santa Clara",
            dono_nome="João Silva",
            dono_wpp="+5516988887777",
            cidade="Franca",
            estado="SP",
            area_total_ha=45.5,
            latitude=-20.5386,
            longitude=-47.4008,
            modulo_dono_ativo=True,
        )
        db.add(fazenda1)
        await db.flush()
        logger.info("Fazenda 1 criada: %s — ID: %s", fazenda1.nome, fazenda1.id)

        # Talhões da Fazenda 1
        talhoes_f1 = [
            Talhao(
                fazenda_id=fazenda1.id,
                nome="Talhão A",
                area_ha=12.0,
                variedade="Catuaí Vermelho 144",
                ano_plantio=2018,
                espacamento="3.5x0.7",
                altitude=1050,
            ),
            Talhao(
                fazenda_id=fazenda1.id,
                nome="Talhão B",
                area_ha=18.5,
                variedade="Obatã",
                ano_plantio=2020,
                espacamento="3.5x0.8",
                altitude=1080,
            ),
            Talhao(
                fazenda_id=fazenda1.id,
                nome="Talhão C",
                area_ha=15.0,
                variedade="Bourbon Amarelo",
                ano_plantio=2015,
                espacamento="4.0x1.0",
                altitude=1020,
            ),
        ]
        for t in talhoes_f1:
            db.add(t)
        await db.flush()
        logger.info("3 talhões criados para %s", fazenda1.nome)

        # ── Fazenda 2 ────────────────────────────────────────────────────────
        fazenda2 = Fazenda(
            agronomo_id=agronomo.id,
            nome="Sítio Boa Vista",
            dono_nome="Maria Fernanda",
            dono_wpp="+5516977776666",
            cidade="Patrocínio Paulista",
            estado="SP",
            area_total_ha=22.0,
            latitude=-20.6300,
            longitude=-47.2800,
            modulo_dono_ativo=False,
        )
        db.add(fazenda2)
        await db.flush()
        logger.info("Fazenda 2 criada: %s — ID: %s", fazenda2.nome, fazenda2.id)

        talhao_f2 = Talhao(
            fazenda_id=fazenda2.id,
            nome="Talhão Principal",
            area_ha=22.0,
            variedade="Mundo Novo",
            ano_plantio=2012,
            espacamento="4.0x1.0",
            altitude=980,
        )
        db.add(talhao_f2)
        await db.flush()

        # ── Mensagem + Visita de exemplo ─────────────────────────────────────
        mensagem = Mensagem(
            agronomo_id=agronomo.id,
            telefone_origem=agronomo.telefone_wpp,
            direcao=DirecaoEnum.recebida,
            tipo=TipoEnum.texto,
            conteudo_texto=(
                "Visitei hoje o Talhão A da Santa Clara. "
                "Encontrei ferrugem em nível médio em cerca de 30% das plantas. "
                "Recomendo aplicação de fungicida sistêmico, epoxiconazol 125g/L, "
                "dose de 0,5L/ha. Próxima visita em 20 dias."
            ),
            processada=True,
            raw_payload={"type": "ReceivedCallback", "source": "seed"},
        )
        db.add(mensagem)
        await db.flush()

        visita = Visita(
            agronomo_id=agronomo.id,
            fazenda_id=fazenda1.id,
            talhao_id=talhoes_f1[0].id,
            mensagem_id=mensagem.id,
            data_visita=date.today(),
            texto_bruto=mensagem.conteudo_texto,
            dados_estruturados={
                "fazenda_identificada": "Fazenda Santa Clara",
                "talhao_identificado": "Talhão A",
                "confianca_identificacao": "alta",
                "data_visita": date.today().isoformat(),
                "estadio_fenologico": "granacao",
                "pragas": [],
                "doencas": [
                    {
                        "nome": "ferrugem alaranjada",
                        "severidade": "media",
                        "area_afetada_pct": 30,
                        "observacao": None,
                    }
                ],
                "recomendacoes": [
                    {
                        "tipo": "aplicacao_quimica",
                        "descricao": "Aplicação de fungicida sistêmico",
                        "produto": "Epoxiconazol",
                        "dose": "0,5L/ha",
                        "area_ha": 12.0,
                        "justificativa": "Ferrugem em nível médio — 30% das plantas",
                    }
                ],
                "observacoes_gerais": None,
                "proxima_visita": (date.today() + timedelta(days=20)).isoformat(),
            },
            status=StatusVisitaEnum.completa,
        )
        db.add(visita)
        await db.commit()

        logger.info("Visita de exemplo criada — ID: %s", visita.id)

    await engine.dispose()

    logger.info("=" * 50)
    logger.info("Seed concluído com sucesso!")
    logger.info("Agrônomo: %s — WhatsApp: %s", agronomo.nome, agronomo.telefone_wpp)
    logger.info("Fazenda 1: %s (ID: %s)", fazenda1.nome, fazenda1.id)
    logger.info("Fazenda 2: %s (ID: %s)", fazenda2.nome, fazenda2.id)
    logger.info("=" * 50)


if __name__ == "__main__":
    asyncio.run(seed())
