"""
ComandoHandler — responde comandos curtos do WhatsApp.

Comandos identificados pelo `comando_parser` são processados aqui,
sem passar pelo pipeline de IA (zero custo de Claude/Whisper).
"""
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import LIMITE_FAZENDAS, settings
from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.visita import StatusVisitaEnum, Visita
from app.services.comando_parser import Comando
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class ComandoHandler:

    def __init__(self, db: AsyncSession, whatsapp) -> None:
        self.db = db
        self.whatsapp = whatsapp

    async def handle(self, comando: Comando, agronomo: Agronomo) -> None:
        """Despacha pro handler do comando."""
        handlers = {
            Comando.AJUDA: self.cmd_ajuda,
            Comando.HISTORICO: self.cmd_historico,
            Comando.FAZENDAS: self.cmd_fazendas,
            Comando.PLANO: self.cmd_plano,
            Comando.STATUS: self.cmd_status,
            Comando.SAUDACAO: self.cmd_saudacao,
            Comando.DESCONHECIDO: self.cmd_desconhecido,
        }
        handler = handlers.get(comando, self.cmd_desconhecido)
        await handler(agronomo)

    async def cmd_ajuda(self, agronomo: Agronomo) -> None:
        nome_curto = agronomo.nome.split()[0]
        msg = (
            f"Oi, {nome_curto}! Aqui o que eu sei fazer 🐦\n\n"
            f"*Registrar visita*\n"
            f"Manda um áudio ou texto descrevendo "
            f"o que você viu na lavoura. Eu estruturo "
            f"tudo e gero o relatório + receituário.\n\n"
            f"*Comandos disponíveis:*\n\n"
            f"📋 *historico* — ver suas últimas visitas\n"
            f"🌱 *fazendas* — ver suas fazendas\n"
            f"💳 *plano* — ver seu plano atual\n"
            f"👤 *status* — ver sua conta\n"
            f"❓ *ajuda* — ver esse menu\n\n"
            f"_Qualquer problema fala com a gente:_\n"
            f"{settings.contact_email}"
        )
        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_historico(self, agronomo: Agronomo) -> None:
        result = await self.db.execute(
            select(Visita)
            .where(Visita.agronomo_id == agronomo.id)
            .where(Visita.status == StatusVisitaEnum.completa)
            .order_by(desc(Visita.data_visita))
            .limit(5)
        )
        visitas = list(result.scalars().all())

        if not visitas:
            await self.whatsapp.send_text(
                agronomo.telefone_wpp,
                "Você ainda não tem visitas registradas. 📋\n\n"
                "Manda um áudio descrevendo sua próxima "
                "visita que eu registro pra você!",
            )
            return

        msg = "*Suas últimas visitas* 📋\n\n"
        for i, v in enumerate(visitas, 1):
            dados = v.dados_estruturados or {}
            n_pragas = len(dados.get("pragas_identificadas", []) or [])
            n_doencas = len(dados.get("doencas_identificadas", []) or [])
            n_recs = len(dados.get("recomendacoes", []) or [])

            fazenda_nome = dados.get(
                "fazenda_identificada", "Fazenda não identificada"
            )
            talhao = dados.get("talhao_identificado") or ""
            data_fmt = v.data_visita.strftime("%d/%m/%Y")

            msg += f"*{i}. {fazenda_nome}*"
            if talhao:
                msg += f" — {talhao}"
            msg += f"\n📅 {data_fmt}"
            if n_pragas or n_doencas:
                msg += f" | ⚠️ {n_pragas}p/{n_doencas}d"
            if n_recs:
                msg += f" | 💊 {n_recs} rec."
            msg += "\n\n"

        msg += "_Manda 'ajuda' pra ver todos os comandos_"
        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_fazendas(self, agronomo: Agronomo) -> None:
        result = await self.db.execute(
            select(Fazenda)
            .where(Fazenda.agronomo_id == agronomo.id)
            .order_by(Fazenda.nome)
        )
        fazendas = list(result.scalars().all())
        total = len(fazendas)
        limite = LIMITE_FAZENDAS.get(agronomo.plano.value, 10)

        if not fazendas:
            await self.whatsapp.send_text(
                agronomo.telefone_wpp,
                "Você ainda não tem fazendas cadastradas. 🌱\n\n"
                "Manda uma visita que eu cadastro "
                "automaticamente!",
            )
            return

        msg = "*Suas fazendas* 🌱\n\n"
        for i, f in enumerate(fazendas, 1):
            dono = f" _(dono: {f.dono_nome})_" if f.dono_nome else ""
            modulo = " 👤" if f.modulo_dono_ativo else ""
            msg += (
                f"{i}. *{f.nome}*{modulo}\n"
                f"   📍 {f.cidade}/{f.estado} "
                f"| {f.area_total_ha:.0f}ha"
                f"{dono}\n\n"
            )

        pct = int((total / limite) * 100) if limite else 0
        blocos = min(10, int(pct / 10))
        barra = "█" * blocos + "░" * (10 - blocos)
        msg += f"_{barra} {total}/{limite} fazendas_"

        if total >= limite:
            msg += (
                "\n\n🚫 *Limite atingido!*\n"
                "Faz upgrade pra cadastrar mais:\n"
                "ticco.com.br/#preco"
            )
        elif total >= int(limite * 0.8):
            msg += "\n\n⚠️ Próximo do limite do plano."

        if any(f.modulo_dono_ativo for f in fazendas):
            msg += "\n\n_👤 = módulo Dono ativo_"

        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_plano(self, agronomo: Agronomo) -> None:
        plano_nome = {
            "free": "Gratuito",
            "basico": "Ticco Básico",
            "completo": "Ticco Completo",
        }.get(agronomo.plano.value, agronomo.plano.value)

        status_val = agronomo.status_pagamento.value
        status_emoji = {
            "trial": "🟡",
            "active": "🟢",
            "past_due": "🔴",
            "canceled": "⚫",
        }.get(status_val, "⚪")
        status_label = {
            "trial": "Período de teste",
            "active": "Ativo",
            "past_due": "Pagamento pendente",
            "canceled": "Cancelado",
        }.get(status_val, "")

        limite = LIMITE_FAZENDAS.get(agronomo.plano.value, 10)

        msg = "*Seu plano* 💳\n\n"
        msg += f"📦 *{plano_nome}*\n"
        msg += f"{status_emoji} {status_label}\n"

        if agronomo.trial_ate and status_val == "trial":
            dias_restantes = (
                agronomo.trial_ate.date() - datetime.now().date()
            ).days
            if dias_restantes > 0:
                msg += f"⏰ Trial acaba em *{dias_restantes} dias*\n"
            else:
                msg += "⏰ Trial expirado\n"

        msg += "\n*Incluído no seu plano:*\n"
        msg += f"✅ Até *{limite} fazendas*\n"
        msg += "✅ Relatórios e receituários ilimitados\n"
        msg += "✅ Histórico completo de visitas\n"

        if agronomo.plano.value == "completo":
            msg += "✅ Módulo Dono (briefing pro proprietário)\n"
            msg += "✅ Receituário com assinatura digital\n"
        else:
            msg += "❌ Módulo Dono (disponível no Completo)\n"
            msg += "❌ Receituário com assinatura digital\n"

        if status_val in ("trial", "active"):
            valor = (
                "R$ 199/mês"
                if agronomo.plano.value == "basico"
                else "R$ 349/mês"
            )
            msg += f"\n💰 *{valor}*"

        if status_val == "past_due":
            msg += (
                "\n\n⚠️ *Pagamento pendente!*\n"
                "Atualiza seu cartão pra continuar:\n"
                "ticco.com.br/#preco"
            )

        if agronomo.plano.value == "basico":
            msg += (
                "\n\n_Quer mais recursos? "
                "Upgrade pro Completo: ticco.com.br/#preco_"
            )

        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_status(self, agronomo: Agronomo) -> None:
        fazendas_result = await self.db.execute(
            select(Fazenda).where(Fazenda.agronomo_id == agronomo.id)
        )
        fazendas = list(fazendas_result.scalars().all())

        visitas_result = await self.db.execute(
            select(Visita)
            .where(Visita.agronomo_id == agronomo.id)
            .where(Visita.status == StatusVisitaEnum.completa)
        )
        visitas = list(visitas_result.scalars().all())

        nome_curto = agronomo.nome.split()[0]
        msg = (
            f"*Sua conta, {nome_curto}* 👤\n\n"
            f"📛 {agronomo.nome}\n"
            f"🏛️ CREA: {agronomo.crea}\n"
            f"📱 {agronomo.telefone_wpp}\n\n"
            f"📊 *Uso do Ticco:*\n"
            f"🌱 {len(fazendas)} fazenda(s) cadastrada(s)\n"
            f"📋 {len(visitas)} visita(s) registrada(s)\n\n"
        )

        if visitas:
            ultima = max(visitas, key=lambda v: v.data_visita)
            msg += (
                f"📅 Última visita: "
                f"{ultima.data_visita.strftime('%d/%m/%Y')}\n\n"
            )

        msg += f"_Manda 'ajuda' pra ver todos os comandos_\n\nEmail: {settings.contact_email}"
        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_saudacao(self, agronomo: Agronomo) -> None:
        hora = datetime.now().hour
        if hora < 12:
            saudacao = "Bom dia"
        elif hora < 18:
            saudacao = "Boa tarde"
        else:
            saudacao = "Boa noite"

        nome_curto = agronomo.nome.split()[0]
        msg = (
            f"{saudacao}, {nome_curto}! 🐦\n\n"
            f"Pronto pra registrar sua próxima visita?\n\n"
            f"Manda um áudio descrevendo o que você viu "
            f"na lavoura que eu processo tudo.\n\n"
            f"_Manda 'ajuda' pra ver outros comandos_"
        )
        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)

    async def cmd_desconhecido(self, agronomo: Agronomo) -> None:
        nome_curto = agronomo.nome.split()[0]
        msg = (
            f"Não entendi, {nome_curto}. 😅\n\n"
            f"Pra registrar uma visita, manda um *áudio* "
            f"descrevendo o que você viu na lavoura.\n\n"
            f"Ou manda *ajuda* pra ver o que eu sei fazer."
        )
        await self.whatsapp.send_text(agronomo.telefone_wpp, msg)
