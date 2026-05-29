"""
Admin API — endpoints internos para o dashboard do fundador.

Proteção: header X-Admin-Key validado contra settings.admin_secret_key.
Não é exposto no /docs em produção (docs_url=None).
"""
import hmac
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import LIMITE_FAZENDAS, settings
from app.models.agronomo import Agronomo, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.visita import StatusVisitaEnum, Visita
from app.workers.briefing_semanal import enviar_briefings_semanais

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _verificar_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Dependência que valida o header X-Admin-Key (compare_digest evita timing attack)."""
    if not settings.admin_secret_key:
        raise HTTPException(status_code=503, detail="Admin não configurado")
    if not x_admin_key or not hmac.compare_digest(x_admin_key, settings.admin_secret_key):
        raise HTTPException(status_code=401, detail="Não autorizado")


# ── Schemas de resposta ───────────────────────────────────────────────────────

class AgronomoAdmin(BaseModel):
    id: uuid.UUID
    nome: str
    crea: str
    telefone_wpp: str
    email: str | None
    plano: str
    status_pagamento: str
    trial_ate: datetime | None
    cidade: str | None  # primeira fazenda, ou None
    total_visitas: int


class VisitaAdmin(BaseModel):
    id: uuid.UUID
    fazenda_nome: str
    agronomo_nome: str
    data_visita: date
    status: str
    pdf_relatorio_url: str | None
    pdf_receituario_url: str | None


class LimitesStats(BaseModel):
    agronomos_no_limite: int
    agronomos_perto_limite: int


class OverviewStats(BaseModel):
    agronomos_trial: int
    agronomos_active: int
    agronomos_canceled: int
    agronomos_past_due: int
    visitas_hoje: int
    visitas_semana: int
    visitas_mes: int
    ultimas_visitas: list[VisitaAdmin]
    ultimos_agronomos: list[AgronomoAdmin]
    limites: LimitesStats


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _carregar_contexto_agronomos(
    agronomos: list[Agronomo], db: AsyncSession
) -> dict[uuid.UUID, tuple[str | None, int]]:
    """
    Pré-carrega cidade (primeira fazenda) e contagem de visitas para uma lista
    de agrônomos numa única query cada, evitando N+1.
    Retorna { agronomo_id: (cidade_or_None, total_visitas) }.
    """
    if not agronomos:
        return {}

    ids = [a.id for a in agronomos]

    # Cidades (primeira fazenda por agrônomo)
    faz_result = await db.execute(
        select(Fazenda.agronomo_id, Fazenda.cidade, Fazenda.created_at)
        .where(Fazenda.agronomo_id.in_(ids))
        .order_by(Fazenda.agronomo_id, Fazenda.created_at)
    )
    cidades: dict[uuid.UUID, str] = {}
    for ag_id, cidade, _ in faz_result:
        cidades.setdefault(ag_id, cidade)

    # Contagem de visitas agrupada
    visitas_result = await db.execute(
        select(Visita.agronomo_id, func.count(Visita.id))
        .where(Visita.agronomo_id.in_(ids))
        .group_by(Visita.agronomo_id)
    )
    contagens: dict[uuid.UUID, int] = {ag_id: total for ag_id, total in visitas_result}

    return {a.id: (cidades.get(a.id), contagens.get(a.id, 0)) for a in agronomos}


def _agronomo_to_schema(
    agronomo: Agronomo, cidade: str | None, total_visitas: int
) -> AgronomoAdmin:
    return AgronomoAdmin(
        id=agronomo.id,
        nome=agronomo.nome,
        crea=agronomo.crea,
        telefone_wpp=agronomo.telefone_wpp,
        email=agronomo.email,
        plano=agronomo.plano.value,
        status_pagamento=agronomo.status_pagamento.value,
        trial_ate=agronomo.trial_ate,
        cidade=cidade,
        total_visitas=total_visitas,
    )


async def _visitas_to_schemas(
    visitas: list[Visita], db: AsyncSession
) -> list[VisitaAdmin]:
    """Materializa lista de VisitaAdmin sem N+1 (carrega fazendas e agrônomos em lote)."""
    if not visitas:
        return []

    fazenda_ids = {v.fazenda_id for v in visitas}
    agronomo_ids = {v.agronomo_id for v in visitas}

    faz_result = await db.execute(select(Fazenda).where(Fazenda.id.in_(fazenda_ids)))
    fazendas = {f.id: f for f in faz_result.scalars()}

    ag_result = await db.execute(select(Agronomo).where(Agronomo.id.in_(agronomo_ids)))
    agronomos = {a.id: a for a in ag_result.scalars()}

    return [
        VisitaAdmin(
            id=v.id,
            fazenda_nome=fazendas[v.fazenda_id].nome if v.fazenda_id in fazendas else "—",
            agronomo_nome=agronomos[v.agronomo_id].nome if v.agronomo_id in agronomos else "—",
            data_visita=v.data_visita,
            status=v.status.value,
            pdf_relatorio_url=v.pdf_relatorio_url,
            pdf_receituario_url=v.pdf_receituario_url,
        )
        for v in visitas
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/overview", response_model=OverviewStats)
async def admin_overview(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
) -> OverviewStats:
    """Visão geral: contagens e últimos registros."""
    agora = datetime.now(timezone.utc)
    hoje = agora.date()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    inicio_mes = hoje.replace(day=1)

    # Contagens por status de pagamento
    async def _contar_agronomo(status: StatusPagamentoEnum) -> int:
        r = await db.execute(
            select(func.count()).where(Agronomo.status_pagamento == status)
        )
        return r.scalar_one() or 0

    async def _contar_visitas(desde: date) -> int:
        r = await db.execute(
            select(func.count()).where(Visita.data_visita >= desde)
        )
        return r.scalar_one() or 0

    visitas_result = await db.execute(
        select(Visita).order_by(Visita.created_at.desc()).limit(5)
    )
    ultimas_visitas_raw = list(visitas_result.scalars().all())

    agron_result = await db.execute(
        select(Agronomo).order_by(Agronomo.created_at.desc()).limit(5)
    )
    ultimos_agronomos_raw = list(agron_result.scalars().all())

    ultimas_visitas = await _visitas_to_schemas(ultimas_visitas_raw, db)
    contexto_ag = await _carregar_contexto_agronomos(ultimos_agronomos_raw, db)
    ultimos_agronomos = [
        _agronomo_to_schema(a, *contexto_ag[a.id]) for a in ultimos_agronomos_raw
    ]

    # Limites — agrônomos no limite ou perto (80%)
    fazenda_counts_result = await db.execute(
        select(Fazenda.agronomo_id, func.count(Fazenda.id).label("total"))
        .group_by(Fazenda.agronomo_id)
    )
    fazenda_counts: dict[uuid.UUID, int] = {
        row.agronomo_id: row.total for row in fazenda_counts_result
    }
    agronomos_plano_result = await db.execute(select(Agronomo.id, Agronomo.plano))
    no_limite = 0
    perto_limite = 0
    for row in agronomos_plano_result:
        total_faz = fazenda_counts.get(row.id, 0)
        limite_faz = LIMITE_FAZENDAS.get(row.plano.value, 10)
        if total_faz >= limite_faz:
            no_limite += 1
        elif total_faz >= int(limite_faz * 0.8):
            perto_limite += 1

    return OverviewStats(
        agronomos_trial=await _contar_agronomo(StatusPagamentoEnum.trial),
        agronomos_active=await _contar_agronomo(StatusPagamentoEnum.active),
        agronomos_canceled=await _contar_agronomo(StatusPagamentoEnum.canceled),
        agronomos_past_due=await _contar_agronomo(StatusPagamentoEnum.past_due),
        visitas_hoje=await _contar_visitas(hoje),
        visitas_semana=await _contar_visitas(inicio_semana),
        visitas_mes=await _contar_visitas(inicio_mes),
        ultimas_visitas=ultimas_visitas,
        ultimos_agronomos=ultimos_agronomos,
        limites=LimitesStats(
            agronomos_no_limite=no_limite,
            agronomos_perto_limite=perto_limite,
        ),
    )


@router.get("/agronomos", response_model=list[AgronomoAdmin])
async def admin_listar_agronomos(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AgronomoAdmin]:
    """Lista agrônomos ordenados por data de cadastro (paginado)."""
    result = await db.execute(
        select(Agronomo)
        .order_by(Agronomo.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    agronomos = list(result.scalars().all())
    contexto = await _carregar_contexto_agronomos(agronomos, db)
    return [_agronomo_to_schema(a, *contexto[a.id]) for a in agronomos]


@router.get("/visitas", response_model=list[VisitaAdmin])
async def admin_listar_visitas(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[VisitaAdmin]:
    """Lista visitas ordenadas pela mais recente (paginado)."""
    result = await db.execute(
        select(Visita)
        .order_by(Visita.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    visitas = list(result.scalars().all())
    return await _visitas_to_schemas(visitas, db)


# ── Briefing manual ───────────────────────────────────────────────────────────

@router.post("/briefing/executar")
async def executar_briefing_manual(
    background_tasks: BackgroundTasks,
    _: None = Depends(_verificar_admin),
) -> dict:
    """
    Dispara o briefing semanal manualmente em background.
    Útil pra testar sem esperar segunda-feira.
    Requer header X-Admin-Key.
    """
    background_tasks.add_task(enviar_briefings_semanais)
    return {
        "status": "iniciado",
        "mensagem": "Briefings sendo enviados em background",
    }


class StatusUpdate(BaseModel):
    status: str  # "active" | "trial" | "canceled" | "past_due"


@router.patch("/agronomos/{agronomo_id}/status", response_model=AgronomoAdmin)
async def admin_atualizar_status(
    agronomo_id: uuid.UUID,
    body: StatusUpdate,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
) -> AgronomoAdmin:
    """Atualiza manualmente o status de pagamento de um agrônomo."""
    agronomo = await db.get(Agronomo, agronomo_id)
    if not agronomo:
        raise HTTPException(status_code=404, detail="Agrônomo não encontrado")

    try:
        agronomo.status_pagamento = StatusPagamentoEnum(body.status)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Status inválido. Use: {[s.value for s in StatusPagamentoEnum]}",
        )

    await db.commit()
    await db.refresh(agronomo)
    logger.info("Admin: status do agrônomo %s alterado para %s", agronomo.nome, body.status)
    contexto = await _carregar_contexto_agronomos([agronomo], db)
    return _agronomo_to_schema(agronomo, *contexto[agronomo.id])


# ── WhatsApp Status ───────────────────────────────────────────────────────────

@router.get("/whatsapp/status")
async def whatsapp_status(
    _: None = Depends(_verificar_admin),
) -> dict:
    """
    Verifica se a instância Evolution API está conectada ao WhatsApp.
    Estados possíveis: open (conectado), close (desconectado), connecting.
    """
    url = (
        f"{settings.evolution_api_url.rstrip('/')}"
        f"/instance/connectionState/{settings.evolution_instance}"
    )
    headers = {"apikey": settings.evolution_api_key}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
            state = (data.get("instance") or {}).get("state", "unknown")
    except httpx.HTTPError as e:
        logger.error("[ADMIN] Erro ao verificar status WhatsApp: %s", e)
        return {
            "instance": settings.evolution_instance,
            "state": "error",
            "connected": False,
            "error": str(e),
        }

    return {
        "instance": settings.evolution_instance,
        "state": state,
        "connected": state == "open",
    }
