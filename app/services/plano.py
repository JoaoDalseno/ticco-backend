"""
PlanoService — validação de limites por plano.

Centraliza as regras de negócio de quota de fazendas,
mensagens de limite e avisos preventivos via WhatsApp.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LIMITE_FAZENDAS
from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda


class PlanoService:

    @staticmethod
    async def verificar_limite_fazendas(
        agronomo: Agronomo,
        db: AsyncSession,
    ) -> tuple[bool, int, int]:
        """
        Verifica se o agrônomo pode cadastrar mais fazendas.

        Retorna:
        - pode_cadastrar: bool
        - fazendas_atuais: int
        - limite_do_plano: int
        """
        result = await db.execute(
            select(func.count(Fazenda.id)).where(
                Fazenda.agronomo_id == agronomo.id
            )
        )
        total = result.scalar() or 0
        limite = LIMITE_FAZENDAS.get(agronomo.plano.value, 10)
        return total < limite, total, limite

    @staticmethod
    def mensagem_limite_atingido(plano: str, total: int, limite: int) -> str:
        """Gera mensagem WhatsApp quando limite de fazendas é atingido."""
        if plano == "basico":
            return (
                f"Você atingiu o limite de *{limite} fazendas* "
                f"do plano Básico. 😕\n\n"
                f"Pra cadastrar mais fazendas, faz upgrade "
                f"pro *Ticco Completo* (até 20 fazendas):\n"
                f"ticco.com.br/#preco\n\n"
                f"Ou fala com o João pra te ajudar:\n"
                f"wa.me/5516999999999"
            )
        return (
            f"Você atingiu o limite de *{limite} fazendas* "
            f"do seu plano. 😕\n\n"
            f"Precisa de mais fazendas? Fala com o João:\n"
            f"wa.me/5516999999999"
        )

    @staticmethod
    async def verificar_e_avisar_limite(
        agronomo: Agronomo,
        db: AsyncSession,
        whatsapp,
    ) -> None:
        """
        Chama após cada cadastro de fazenda nova.
        Envia aviso proativo quando o agrônomo atinge exatamente 80% do limite.
        """
        _, total, limite = await PlanoService.verificar_limite_fazendas(agronomo, db)

        if total == int(limite * 0.8):
            await whatsapp.send_text(
                agronomo.telefone_wpp,
                f"⚠️ Você tem *{total} de {limite} fazendas* "
                f"cadastradas no seu plano.\n\n"
                f"Quando atingir o limite, não conseguirá "
                f"cadastrar novas fazendas.\n\n"
                f"Quer fazer upgrade? ticco.com.br/#preco",
            )
