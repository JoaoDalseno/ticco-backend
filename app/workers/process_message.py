"""
Worker de processamento de mensagens — pipeline completo (Fases 3-5).

Fluxo:
  1. Carrega mensagem do banco
  2. Identifica agrônomo pelo telefone
  3. Verifica plano ativo
  4. Se áudio: baixa + transcreve com Groq
  5. Carrega fazendas do agrônomo
  6. Extrai dados com Claude
  7. Identifica fazenda/talhão no banco
  8. Salva Visita no banco
  9. Envia resumo formatado ao agrônomo
 10. Marca mensagem como processada
"""
import uuid
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.mensagem import Mensagem
from app.models.talhao import Talhao
from app.models.visita import StatusVisitaEnum, Visita
from app.services.ai_processor import AIProcessor
from app.services.transcription import TranscriptionService
from app.services.whatsapp.zapi import ZAPIWhatsAppService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

whatsapp = ZAPIWhatsAppService()
transcription = TranscriptionService()
ai_processor = AIProcessor()

MSG_RECEBIDO = "Recebi! Tô processando sua visita... 🐦"

MSG_ERRO = (
    "Opa, tive um problema aqui 😅\n"
    "Não consegui processar sua mensagem.\n"
    "Pode tentar de novo? Se persistir, chama o João."
)

MSG_INATIVO = (
    "Opa! Sua conta ainda não tá ativa. 😕\n"
    "Fala com o João pra ativar:\n"
    "wa.me/5516999999999"
)

MSG_NAO_CADASTRADO = (
    "Salve! Aqui é o Ticco 🐦\n\n"
    "Não te reconheci ainda. Você é agrônomo consultor de café?\n"
    "Responde *sim* que eu te cadastro rapidinho."
)


async def process_message(mensagem_id: uuid.UUID, db: AsyncSession) -> None:
    """Pipeline completo: mensagem → visita estruturada."""
    try:
        # 1. Carrega mensagem
        mensagem = await db.get(Mensagem, mensagem_id)
        if not mensagem:
            logger.error(f"Mensagem {mensagem_id} não encontrada")
            return

        phone = mensagem.telefone_origem

        # 2. Identifica agrônomo
        result = await db.execute(
            select(Agronomo).where(Agronomo.telefone_wpp == phone)
        )
        agronomo = result.scalar_one_or_none()

        if not agronomo:
            await whatsapp.send_text(phone, MSG_NAO_CADASTRADO)
            mensagem.processada = True
            await db.commit()
            return

        # 3. Verifica plano ativo
        planos_ativos = [StatusPagamentoEnum.trial, StatusPagamentoEnum.active]
        if agronomo.status_pagamento not in planos_ativos:
            await whatsapp.send_text(phone, MSG_INATIVO)
            mensagem.processada = True
            await db.commit()
            return

        # Confirma recebimento imediatamente
        await whatsapp.send_text(phone, MSG_RECEBIDO)

        # 4. Se áudio: baixa e transcreve
        texto_bruto = mensagem.conteudo_texto or ""

        if mensagem.tipo.value == "audio" and mensagem.midia_url:
            logger.info(f"Baixando áudio: {mensagem.midia_url}")
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(mensagem.midia_url)
                resp.raise_for_status()
                audio_bytes = resp.content

            texto_bruto = await transcription.transcribe(
                audio_bytes=audio_bytes,
                language="pt",
                filename="audio.ogg",
            )
            mensagem.transcricao = texto_bruto
            await db.commit()
            logger.info(f"Transcrição: {texto_bruto[:100]}...")

        if not texto_bruto.strip():
            await whatsapp.send_text(
                phone,
                "Não consegui entender a mensagem. "
                "Tenta mandar um áudio ou texto descrevendo a visita. 🎙️",
            )
            mensagem.processada = True
            await db.commit()
            return

        # 5. Carrega fazendas do agrônomo
        fazendas_result = await db.execute(
            select(Fazenda).where(Fazenda.agronomo_id == agronomo.id)
        )
        fazendas = list(fazendas_result.scalars().all())

        fazendas_contexto = []
        for f in fazendas:
            talhoes_result = await db.execute(
                select(Talhao).where(Talhao.fazenda_id == f.id, Talhao.ativo == True)  # noqa: E712
            )
            talhoes = list(talhoes_result.scalars().all())
            fazendas_contexto.append({
                "nome": f.nome,
                "cidade": f.cidade,
                "area_ha": f.area_total_ha,
                "talhoes": [
                    {"nome": t.nome, "area_ha": t.area_ha, "variedade": t.variedade}
                    for t in talhoes
                ],
            })

        # 6. Extrai dados com Claude
        logger.info("Processando visita com Claude...")
        dados = await ai_processor.extract_visita_data(
            texto_bruto=texto_bruto,
            fazendas_contexto=fazendas_contexto,
        )

        # 7. Identifica fazenda e talhão no banco
        fazenda_db: Fazenda | None = None
        talhao_db: Talhao | None = None

        if dados.fazenda_identificada:
            for f in fazendas:
                if dados.fazenda_identificada.lower() in f.nome.lower():
                    fazenda_db = f
                    break

        # Fallback: usa primeira fazenda se só há uma
        if not fazenda_db and len(fazendas) == 1:
            fazenda_db = fazendas[0]

        if not fazenda_db:
            await whatsapp.send_text(
                phone,
                "⚠️ Não identifiquei a fazenda no seu relato. "
                "Mencione o nome da fazenda e tente novamente.",
            )
            mensagem.processada = True
            await db.commit()
            return

        if dados.talhao_identificado:
            talhoes_result = await db.execute(
                select(Talhao).where(Talhao.fazenda_id == fazenda_db.id)
            )
            for t in talhoes_result.scalars().all():
                if dados.talhao_identificado.lower() in t.nome.lower():
                    talhao_db = t
                    break

        # 8. Salva Visita no banco
        visita = Visita(
            id=uuid.uuid4(),
            agronomo_id=agronomo.id,
            fazenda_id=fazenda_db.id,
            talhao_id=talhao_db.id if talhao_db else None,
            mensagem_id=mensagem.id,
            data_visita=date.today(),
            texto_bruto=texto_bruto,
            dados_estruturados=dados.model_dump(),
            status=StatusVisitaEnum.processando,
        )
        db.add(visita)
        await db.commit()
        await db.refresh(visita)

        logger.info(f"Visita {visita.id} salva no banco")

        # 9. Envia resumo formatado ao agrônomo
        resumo = await ai_processor.gerar_resumo_whatsapp(
            dados=dados,
            nome_agronomo=agronomo.nome,
        )
        await whatsapp.send_text(phone, resumo)

        # 10. Marca como processada
        mensagem.processada = True
        visita.status = StatusVisitaEnum.completa
        await db.commit()

        logger.info(
            f"Pipeline concluído — visita {visita.id} — agrônomo {agronomo.nome}"
        )

    except Exception as e:
        logger.error(f"Erro no pipeline da mensagem {mensagem_id}: {e}", exc_info=True)
        try:
            result = await db.execute(select(Mensagem).where(Mensagem.id == mensagem_id))
            mensagem = result.scalar_one_or_none()
            if mensagem:
                await whatsapp.send_text(mensagem.telefone_origem, MSG_ERRO)
                mensagem.processada = True
                await db.commit()
        except Exception:
            pass
