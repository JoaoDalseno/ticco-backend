"""
Admin API — endpoints internos para o dashboard do fundador.

Proteção: header X-Admin-Key validado contra settings.admin_secret_key.
Não é exposto no /docs em produção (docs_url=None).
"""
import logging
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.config import settings
from app.models.agronomo import Agronomo, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.visita import StatusVisitaEnum, Visita

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ── Auth ──────────────────────────────────────────────────────────────────────

def _verificar_admin(x_admin_key: str | None = Header(default=None)) -> None:
    """Dependência que valida o header X-Admin-Key."""
    if not settings.admin_secret_key:
        raise HTTPException(status_code=503, detail="Admin não configurado")
    if not x_admin_key or x_admin_key != settings.admin_secret_key:
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


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _agronomo_to_schema(agronomo: Agronomo, db: AsyncSession) -> AgronomoAdmin:
    """Monta AgronomoAdmin buscando cidade e contagem de visitas."""
    # Primeira fazenda para extrair cidade
    faz_result = await db.execute(
        select(Fazenda)
        .where(Fazenda.agronomo_id == agronomo.id)
        .order_by(Fazenda.created_at)
        .limit(1)
    )
    fazenda = faz_result.scalar_one_or_none()

    # Contagem de visitas
    count_result = await db.execute(
        select(func.count()).where(Visita.agronomo_id == agronomo.id)
    )
    total_visitas = count_result.scalar_one() or 0

    return AgronomoAdmin(
        id=agronomo.id,
        nome=agronomo.nome,
        crea=agronomo.crea,
        telefone_wpp=agronomo.telefone_wpp,
        email=agronomo.email,
        plano=agronomo.plano.value,
        status_pagamento=agronomo.status_pagamento.value,
        trial_ate=agronomo.trial_ate,
        cidade=fazenda.cidade if fazenda else None,
        total_visitas=total_visitas,
    )


async def _visita_to_schema(visita: Visita, db: AsyncSession) -> VisitaAdmin:
    """Monta VisitaAdmin com nome da fazenda e agrônomo."""
    fazenda = await db.get(Fazenda, visita.fazenda_id)
    agronomo = await db.get(Agronomo, visita.agronomo_id)

    return VisitaAdmin(
        id=visita.id,
        fazenda_nome=fazenda.nome if fazenda else "—",
        agronomo_nome=agronomo.nome if agronomo else "—",
        data_visita=visita.data_visita,
        status=visita.status.value,
        pdf_relatorio_url=visita.pdf_relatorio_url,
        pdf_receituario_url=visita.pdf_receituario_url,
    )


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

    # Últimas 5 visitas
    visitas_result = await db.execute(
        select(Visita).order_by(Visita.created_at.desc()).limit(5)
    )
    ultimas_visitas_raw = visitas_result.scalars().all()

    # Últimos 5 agrônomos
    agron_result = await db.execute(
        select(Agronomo).order_by(Agronomo.created_at.desc()).limit(5)
    )
    ultimos_agronomo_raw = agron_result.scalars().all()

    ultimas_visitas = [await _visita_to_schema(v, db) for v in ultimas_visitas_raw]
    ultimos_agronomos = [await _agronomo_to_schema(a, db) for a in ultimos_agronomo_raw]

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
    )


@router.get("/agronomos", response_model=list[AgronomoAdmin])
async def admin_listar_agronomos(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
) -> list[AgronomoAdmin]:
    """Lista todos os agrônomos ordenados por data de cadastro."""
    result = await db.execute(select(Agronomo).order_by(Agronomo.created_at.desc()))
    agronomos = result.scalars().all()
    return [await _agronomo_to_schema(a, db) for a in agronomos]


@router.get("/visitas", response_model=list[VisitaAdmin])
async def admin_listar_visitas(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(_verificar_admin),
) -> list[VisitaAdmin]:
    """Lista todas as visitas ordenadas pela mais recente."""
    result = await db.execute(select(Visita).order_by(Visita.created_at.desc()))
    visitas = result.scalars().all()
    return [await _visita_to_schema(v, db) for v in visitas]


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
    return await _agronomo_to_schema(agronomo, db)
