"""
Notificações operacionais para o fundador via WhatsApp.

Cobre quatro eventos críticos do negócio:
  - Erro no pipeline de visita → saber imediatamente
  - Novo agrônomo cadastrado   → acompanhar crescimento
  - Novo pagamento confirmado  → celebrar e monitorar receita
  - Trial expirado sem conversão → acionar follow-up

Design:
  - Recebe `whatsapp` no construtor (testável por injeção)
  - Falha silenciosa: erro na notificação nunca quebra o fluxo principal
  - Sem-op quando FOUNDER_PHONE não está configurado
"""
from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class NotificacaoFundador:
    """
    Notifica o fundador (João) via WhatsApp
    quando algo importante acontece.
    """

    def __init__(self, whatsapp) -> None:
        self.whatsapp = whatsapp
        self.founder_phone = settings.founder_phone

    async def erro_pipeline(
        self,
        agronomo_nome: str,
        agronomo_phone: str,
        erro: str,
        mensagem_id: str,
    ) -> None:
        """Notifica erro no pipeline de visita."""
        if not self.founder_phone:
            return

        msg = (
            f"🚨 *Erro no pipeline*\n\n"
            f"Agrônomo: {agronomo_nome}\n"
            f"Tel: {agronomo_phone}\n"
            f"Mensagem ID: {mensagem_id}\n\n"
            f"Erro: {erro[:200]}"
        )
        await self._enviar(msg)

    async def novo_cadastro(
        self,
        nome: str,
        crea: str,
        cidade: str,
        phone: str,
    ) -> None:
        """Notifica novo agrônomo cadastrado."""
        if not self.founder_phone:
            return

        msg = (
            f"🐦 *Novo agrônomo cadastrado!*\n\n"
            f"Nome: {nome}\n"
            f"CREA: {crea}\n"
            f"Cidade: {cidade}\n"
            f"Tel: {phone}"
        )
        await self._enviar(msg)

    async def novo_pagamento(
        self,
        nome: str,
        plano: str,
        valor: float,
    ) -> None:
        """Notifica novo pagamento confirmado."""
        if not self.founder_phone:
            return

        msg = (
            f"💰 *Novo pagamento!*\n\n"
            f"Cliente: {nome}\n"
            f"Plano: {plano}\n"
            f"Valor: R$ {valor:.2f}/mês\n\n"
            f"🎉 Bora!"
        )
        await self._enviar(msg)

    async def trial_expirado(
        self,
        nome: str,
        phone: str,
        dias_sem_pagar: int,
    ) -> None:
        """Notifica trial expirado sem conversão."""
        if not self.founder_phone:
            return

        msg = (
            f"⏰ *Trial expirado sem conversão*\n\n"
            f"Nome: {nome}\n"
            f"Tel: {phone}\n"
            f"Dias sem pagar: {dias_sem_pagar}\n\n"
            f"_Hora de fazer follow-up?_"
        )
        await self._enviar(msg)

    async def _enviar(self, msg: str) -> None:
        try:
            await self.whatsapp.send_text(self.founder_phone, msg)
        except Exception as e:
            # Falha silenciosa — notificação não deve quebrar o fluxo principal
            logger.error("Erro ao notificar fundador: %s", e)
