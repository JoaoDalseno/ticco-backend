"""
Webhook Stripe — trata eventos de assinatura e pagamento.

Endpoint: POST /webhooks/stripe

Eventos tratados:
  customer.subscription.created  → ativa plano
  customer.subscription.deleted  → cancela plano
  invoice.payment_failed         → marca como inadimplente
  customer.subscription.trial_will_end → avisa fim do trial

Sempre retorna 200 para evitar reenvios infinitos pela Stripe.
"""
import logging

import stripe
from fastapi import APIRouter, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo, StatusPagamentoEnum
from app.services.whatsapp.zapi import ZAPIWhatsAppService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks")

whatsapp = ZAPIWhatsAppService()


# ── Mensagens WhatsApp ────────────────────────────────────────────────────────

MSG_ATIVADO = (
    "Pagamento confirmado! Seu plano Ticco "
    "Completo está ativo. 🎉\n\n"
    "Pode mandar seu próximo relato de visita quando quiser. 🐦"
)

MSG_CANCELADO = (
    "Sua assinatura foi cancelada. 😕\n\n"
    "Se foi engano, fala com o João diretamente."
)

MSG_TRIAL_ENDING = (
    "Seu trial acaba em 3 dias. ⏰\n\n"
    "Assina aqui pra continuar usando o Ticco:\n"
    "ticco.com.br/#preco"
)


def _msg_pagamento_falhou(link: str) -> str:
    return (
        "Tivemos um problema no seu pagamento. 😟\n\n"
        f"Atualiza o cartão no link:\n{link}"
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _buscar_agronomo_por_customer(
    customer_id: str, db: AsyncSession
) -> Agronomo | None:
    """Encontra o agrônomo pelo stripe_customer_id."""
    result = await db.execute(
        select(Agronomo).where(Agronomo.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _atualizar_status(
    agronomo: Agronomo,
    novo_status: StatusPagamentoEnum,
    db: AsyncSession,
) -> None:
    agronomo.status_pagamento = novo_status
    await db.commit()
    logger.info(
        "Status do agrônomo %s atualizado para %s",
        agronomo.nome,
        novo_status.value,
    )


# ── Handlers por evento ───────────────────────────────────────────────────────

async def _handle_subscription_created(
    event: stripe.Event, db: AsyncSession
) -> None:
    subscription = event.data.object
    customer_id = subscription.get("customer")
    agronomo = await _buscar_agronomo_por_customer(customer_id, db)
    if not agronomo:
        logger.warning("subscription.created: customer %s não encontrado", customer_id)
        return

    # Salva também o subscription_id para referência futura
    agronomo.stripe_subscription_id = subscription.get("id")
    await _atualizar_status(agronomo, StatusPagamentoEnum.active, db)
    await whatsapp.send_text(agronomo.telefone_wpp, MSG_ATIVADO)


async def _handle_subscription_deleted(
    event: stripe.Event, db: AsyncSession
) -> None:
    subscription = event.data.object
    customer_id = subscription.get("customer")
    agronomo = await _buscar_agronomo_por_customer(customer_id, db)
    if not agronomo:
        logger.warning("subscription.deleted: customer %s não encontrado", customer_id)
        return

    await _atualizar_status(agronomo, StatusPagamentoEnum.canceled, db)
    await whatsapp.send_text(agronomo.telefone_wpp, MSG_CANCELADO)


async def _handle_payment_failed(
    event: stripe.Event, db: AsyncSession
) -> None:
    invoice = event.data.object
    customer_id = invoice.get("customer")
    agronomo = await _buscar_agronomo_por_customer(customer_id, db)
    if not agronomo:
        logger.warning("payment_failed: customer %s não encontrado", customer_id)
        return

    await _atualizar_status(agronomo, StatusPagamentoEnum.past_due, db)

    # hosted_invoice_url é o link da fatura com opção de pagar/atualizar cartão
    link = invoice.get("hosted_invoice_url") or "ticco.com.br"
    await whatsapp.send_text(agronomo.telefone_wpp, _msg_pagamento_falhou(link))


async def _handle_trial_will_end(
    event: stripe.Event, db: AsyncSession
) -> None:
    subscription = event.data.object
    customer_id = subscription.get("customer")
    agronomo = await _buscar_agronomo_por_customer(customer_id, db)
    if not agronomo:
        logger.warning("trial_will_end: customer %s não encontrado", customer_id)
        return

    await whatsapp.send_text(agronomo.telefone_wpp, MSG_TRIAL_ENDING)


_HANDLERS = {
    "customer.subscription.created": _handle_subscription_created,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.payment_failed": _handle_payment_failed,
    "customer.subscription.trial_will_end": _handle_trial_will_end,
}


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/stripe")
async def webhook_stripe(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict:
    """
    Recebe eventos da Stripe. Sempre retorna 200 para evitar
    que a Stripe reenvie o mesmo evento em loop.
    """
    payload = await request.body()

    # Valida assinatura HMAC — protege contra requisições forjadas
    if settings.stripe_webhook_secret:
        try:
            event = stripe.Webhook.construct_event(
                payload=payload,
                sig_header=stripe_signature or "",
                secret=settings.stripe_webhook_secret,
            )
        except stripe.SignatureVerificationError:
            logger.warning("Stripe webhook: assinatura inválida")
            return {"ok": True}
        except Exception as exc:
            logger.error("Stripe webhook: erro ao verificar assinatura: %s", exc)
            return {"ok": True}
    else:
        # Sem secret configurado (desenvolvimento) — parseia sem validar
        try:
            import json
            event = stripe.Event.construct_from(
                json.loads(payload), stripe.api_key
            )
        except Exception as exc:
            logger.error("Stripe webhook: payload inválido: %s", exc)
            return {"ok": True}

    event_type: str = event.get("type", "")
    handler = _HANDLERS.get(event_type)

    if handler is None:
        # Evento não tratado — ignora silenciosamente
        logger.debug("Stripe webhook: evento ignorado — %s", event_type)
        return {"ok": True}

    logger.info("Stripe webhook: processando evento %s", event_type)

    try:
        async with AsyncSessionLocal() as db:
            await handler(event, db)
    except Exception as exc:
        # Loga mas retorna 200 — evita reenvio infinito
        logger.error(
            "Erro ao processar evento Stripe %s: %s", event_type, exc, exc_info=True
        )

    return {"ok": True}
