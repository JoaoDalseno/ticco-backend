"""
POST /v1/fazendas — cadastro de fazenda do agrônomo autenticado.

Autenticação: Bearer JWT (Authorization header).
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_agronomo, get_db
from app.config import LIMITE_FAZENDAS
from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.schemas.fazenda import FazendaCreate, FazendaRead
from app.services.plano import PlanoService
from app.services.whatsapp.zapi import ZAPIWhatsAppService

router = APIRouter(prefix="/v1/fazendas", tags=["fazendas"])

_whatsapp = ZAPIWhatsAppService()


@router.post("", response_model=FazendaRead, status_code=201)
async def criar_fazenda(
    dados: FazendaCreate,
    db: AsyncSession = Depends(get_db),
    agronomo: Agronomo = Depends(get_current_agronomo),
) -> Fazenda:
    """
    Cadastra uma nova fazenda para o agrônomo do JWT.
    Retorna 403 se o limite do plano já foi atingido.

    Para evitar race condition entre dois POSTs paralelos do mesmo agrônomo,
    a contagem e o INSERT acontecem na mesma transação, com lock pessimista
    na linha do agrônomo (SELECT … FOR UPDATE).
    """
    # Lock pessimista no agrônomo — serializa cadastros paralelos do mesmo dono
    await db.execute(
        select(Agronomo.id).where(Agronomo.id == agronomo.id).with_for_update()
    )

    total_result = await db.execute(
        select(func.count(Fazenda.id)).where(Fazenda.agronomo_id == agronomo.id)
    )
    total = total_result.scalar_one() or 0
    limite = LIMITE_FAZENDAS.get(agronomo.plano.value, 10)

    if total >= limite:
        raise HTTPException(
            status_code=403,
            detail={
                "erro": "limite_fazendas_atingido",
                "total": total,
                "limite": limite,
                "plano": agronomo.plano.value,
                "mensagem": (
                    f"Limite de {limite} fazendas atingido "
                    f"no plano {agronomo.plano.value}"
                ),
            },
        )

    fazenda = Fazenda(
        id=uuid.uuid4(),
        agronomo_id=agronomo.id,
        **dados.model_dump(),
    )
    db.add(fazenda)
    await db.commit()
    await db.refresh(fazenda)

    await PlanoService.verificar_e_avisar_limite(agronomo, db, _whatsapp)
    return fazenda
