"""
Checkout Stripe — cria sessão de pagamento para assinatura.

Endpoint: POST /v1/checkout

Fluxo:
  1. Agrônomo autenticado envia {"plano": "basico" | "completo"}
  2. Cria (ou reutiliza) Customer no Stripe
  3. Cria Checkout Session em modo "subscription"
  4. Retorna URL da sessão para o frontend redirecionar o usuário

Após o pagamento, Stripe envia webhook → customer.subscription.created
que ativa o plano automaticamente.
"""
import asyncio
import logging

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Literal

from app.api.deps import get_current_agronomo, get_db
from app.config import settings
from app.models.agronomo import Agronomo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1")


# ── Schemas ───────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plano: Literal["basico", "completo"]


class CheckoutResponse(BaseModel):
    checkout_url: str


# ── Mapa plano → Price ID ─────────────────────────────────────────────────────

def _price_id_para_plano(plano: str) -> str:
    """Retorna o Stripe Price ID correspondente ao plano. Levanta 503 se não configurado."""
    mapa = {
        "basico": settings.stripe_price_basico,
        "completo": settings.stripe_price_completo,
    }
    price_id = mapa.get(plano, "")
    if not price_id:
        raise HTTPException(
            status_code=503,
            detail=f"Price ID para o plano '{plano}' não configurado (STRIPE_PRICE_{plano.upper()})",
        )
    return price_id


# ── Helpers Stripe (wrappados em to_thread — SDK é síncrono) ──────────────────

async def _get_or_create_customer(agronomo: Agronomo, db: AsyncSession) -> str:
    """
    Retorna o stripe_customer_id do agrônomo.
    Cria um novo Customer se ainda não existir e persiste no banco.
    """
    if agronomo.stripe_customer_id:
        return agronomo.stripe_customer_id

    stripe.api_key = settings.stripe_secret_key

    customer = await asyncio.to_thread(
        stripe.Customer.create,
        name=agronomo.nome,
        email=agronomo.email or "",
        metadata={"agronomo_id": str(agronomo.id)},
    )

    agronomo.stripe_customer_id = customer.id
    await db.commit()
    logger.info("Stripe Customer criado — agronomo=%s customer=%s", agronomo.nome, customer.id)

    return customer.id


async def _criar_checkout_session(
    customer_id: str,
    price_id: str,
    agronomo_id: str,
) -> str:
    """Cria Checkout Session e retorna a URL de pagamento."""
    stripe.api_key = settings.stripe_secret_key

    success_url = f"{settings.frontend_url}/sucesso?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{settings.frontend_url}/#preco"

    session = await asyncio.to_thread(
        stripe.checkout.Session.create,
        customer=customer_id,
        mode="subscription",
        line_items=[{"price": price_id, "quantity": 1}],
        success_url=success_url,
        cancel_url=cancel_url,
        metadata={"agronomo_id": agronomo_id},
        # Pré-preenche e-mail no checkout
        customer_update={"address": "auto"},
    )

    logger.info(
        "Checkout Session criada — agronomo_id=%s plano_price=%s session=%s",
        agronomo_id,
        price_id,
        session.id,
    )
    return session.url


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/checkout", response_model=CheckoutResponse)
async def criar_checkout(
    body: CheckoutRequest,
    agronomo: Agronomo = Depends(get_current_agronomo),
    db: AsyncSession = Depends(get_db),
) -> CheckoutResponse:
    """
    Cria uma Stripe Checkout Session para o agrônomo autenticado.

    Requer header: `Authorization: Bearer <token>`
    Body: `{"plano": "basico" | "completo"}`

    Retorna a URL para redirecionar o usuário ao checkout do Stripe.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Pagamentos não configurados")

    price_id = _price_id_para_plano(body.plano)

    try:
        customer_id = await _get_or_create_customer(agronomo, db)
        checkout_url = await _criar_checkout_session(
            customer_id=customer_id,
            price_id=price_id,
            agronomo_id=str(agronomo.id),
        )
    except HTTPException:
        raise
    except stripe.StripeError as exc:
        logger.error("Erro Stripe ao criar checkout — agronomo=%s: %s", agronomo.nome, exc)
        raise HTTPException(status_code=502, detail="Erro ao criar sessão de pagamento")
    except Exception as exc:
        logger.error("Erro inesperado no checkout — agronomo=%s: %s", agronomo.nome, exc)
        raise HTTPException(status_code=500, detail="Erro interno ao criar checkout")

    return CheckoutResponse(checkout_url=checkout_url)
