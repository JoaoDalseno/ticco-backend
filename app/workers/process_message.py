"""
Worker de processamento de mensagens — pipeline da visita.

Pré-condição: o webhook já intercepta onboarding e número desconhecido,
então aqui o agrônomo sempre existe.

Fluxo:
  1. Carrega mensagem
  2. Identifica agrônomo + verifica plano ativo
  3. Comando curto? → ComandoHandler e retorna
  4. Áudio? → valida URL (SSRF guard), baixa com limite, transcreve
  5. Carrega fazendas + talhões
  6. Extrai dados com Claude
  7. Identifica fazenda/talhão
  8. Salva Visita
  9. Gera PDFs + upload Storage
 10. Envia resumo + PDFs via WhatsApp
"""
import asyncio
import uuid
from datetime import date

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.agronomo import Agronomo, PlanoEnum, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.mensagem import Mensagem
from app.models.talhao import Talhao
from app.models.visita import StatusVisitaEnum, Visita
from app.services.ai_processor import AIProcessor
from app.services.comando_handler import ComandoHandler
from app.services.comando_parser import Comando, identificar_comando
from app.services.icp_brasil import ICPBrasilService
from app.services.notificacao_fundador import NotificacaoFundador
from app.services.pdf_generator import gerar_receituario, gerar_relatorio
from app.services.storage import StorageService
from app.services.transcription import MAX_AUDIO_BYTES, TranscriptionService, validar_url_audio
from app.services.whatsapp.evolution import EvolutionWhatsAppService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

whatsapp = EvolutionWhatsAppService()
transcription = TranscriptionService()
ai_processor = AIProcessor()
storage = StorageService()
icp = ICPBrasilService()

MSG_RECEBIDO = "Recebi! Tô processando sua visita... 🐦"

MSG_ERRO = (
    "Opa, tive um problema aqui 😅\n"
    "Não consegui processar sua mensagem.\n"
    f"Pode tentar de novo? Se persistir: {settings.contact_email}"
)

MSG_INATIVO = (
    "Opa! Sua conta ainda não tá ativa. 😕\n"
    f"Fala com a gente pra ativar:\n{settings.contact_email}"
)

# Cota diária de visitas por plano (A04 — Insecure Design / proteção de custo de IA)
_COTA_DIARIA: dict[str, int] = {
    PlanoEnum.free.value: 5,
    PlanoEnum.basico.value: 30,
    PlanoEnum.completo.value: 80,
}
_COTA_DIARIA_PADRAO = 5  # fallback conservador

MSG_COTA_ATINGIDA = (
    "Você atingiu o limite diário de visitas do seu plano. 😅\n"
    "As visitas são reiniciadas à meia-noite. "
    "Para aumentar seu limite, acesse seu plano em useticco.com."
)


async def _verificar_cota_diaria(agronomo: Agronomo, db: AsyncSession) -> bool:
    """
    Retorna True se o agrônomo ainda tem cota disponível hoje.
    Conta visitas com status != 'erro' criadas hoje (data_visita).
    """
    plano_val = agronomo.plano.value if agronomo.plano else PlanoEnum.free.value
    cota = _COTA_DIARIA.get(plano_val, _COTA_DIARIA_PADRAO)

    hoje = date.today()
    result = await db.execute(
        select(func.count(Visita.id)).where(
            Visita.agronomo_id == agronomo.id,
            Visita.data_visita == hoje,
            Visita.status != StatusVisitaEnum.erro,
        )
    )
    visitas_hoje: int = result.scalar_one()
    return visitas_hoje < cota


async def process_message(mensagem_id: uuid.UUID, db: AsyncSession) -> None:
    """Pipeline completo: mensagem → visita estruturada."""
    # Rastreia contexto para o bloco except — podem não ser definidos se o erro ocorrer cedo
    _agronomo_nome: str = "Desconhecido"
    _agronomo_phone: str = "desconhecido"

    try:
        # 1. Carrega mensagem
        mensagem = await db.get(Mensagem, mensagem_id)
        if not mensagem:
            logger.error(f"Mensagem {mensagem_id} não encontrada")
            return

        phone = mensagem.telefone_origem
        texto_recebido = mensagem.conteudo_texto or ""

        # O webhook intercepta onboarding e cadastro; aqui o agrônomo sempre existe.
        result = await db.execute(
            select(Agronomo).where(Agronomo.telefone_wpp == phone)
        )
        agronomo = result.scalar_one_or_none()
        if not agronomo:
            logger.warning("process_message chamado para número sem agrônomo: %s", phone)
            mensagem.processada = True
            await db.commit()
            return

        # Atualiza contexto para notificações de erro
        _agronomo_nome = agronomo.nome
        _agronomo_phone = phone

        # Verifica plano ativo
        planos_ativos = [StatusPagamentoEnum.trial, StatusPagamentoEnum.active]
        if agronomo.status_pagamento not in planos_ativos:
            await whatsapp.send_text(phone, MSG_INATIVO)
            mensagem.processada = True
            await db.commit()
            return

        # Comandos de texto curtos (ajuda/historico/fazendas/plano/status/...).
        # Áudio nunca é comando — sempre vai pro pipeline de visita.
        if mensagem.tipo.value != "audio":
            comando = identificar_comando(texto_recebido)
            if comando != Comando.VISITA:
                handler = ComandoHandler(db=db, whatsapp=whatsapp)
                await handler.handle(comando, agronomo)
                mensagem.processada = True
                await db.commit()
                return

        # Cota diária de visitas por plano (proteção de custo de IA — A04)
        if not await _verificar_cota_diaria(agronomo, db):
            logger.warning(
                "[QUOTA] Cota diária atingida agronomo_id=%s plano=%s",
                agronomo.id,
                agronomo.status_pagamento,
            )
            await whatsapp.send_text(phone, MSG_COTA_ATINGIDA)
            mensagem.processada = True
            await db.commit()
            return

        # 4. Se áudio: valida URL, baixa com limite e transcreve
        texto_bruto = mensagem.conteudo_texto or ""

        if mensagem.tipo.value == "audio" and mensagem.midia_url:
            try:
                validar_url_audio(mensagem.midia_url)
            except ValueError as e:
                logger.warning(f"URL de áudio rejeitada ({phone}): {e}")
                await whatsapp.send_text(
                    phone,
                    "Não consegui acessar o áudio. Pode mandar de novo? 🎙️",
                )
                mensagem.processada = True
                await db.commit()
                return

            await whatsapp.send_text(phone, MSG_RECEBIDO)

            logger.info(f"Baixando áudio: {mensagem.midia_url}")
            audio_bytes = b""
            async with httpx.AsyncClient(timeout=60) as client:
                async with client.stream("GET", mensagem.midia_url) as resp:
                    resp.raise_for_status()
                    declared_len = resp.headers.get("content-length")
                    if declared_len and int(declared_len) > MAX_AUDIO_BYTES:
                        raise ValueError(
                            f"Áudio excede limite ({declared_len} > {MAX_AUDIO_BYTES} bytes)"
                        )
                    async for chunk in resp.aiter_bytes():
                        audio_bytes += chunk
                        if len(audio_bytes) > MAX_AUDIO_BYTES:
                            raise ValueError(
                                f"Áudio excedeu {MAX_AUDIO_BYTES} bytes durante download"
                            )

            texto_bruto = await transcription.transcribe(
                audio_bytes=audio_bytes,
                language="pt",
                filename="audio.ogg",
            )
            mensagem.transcricao = texto_bruto
            await db.commit()
            logger.info(f"Transcrição: {texto_bruto[:100]}...")
        else:
            # Texto longo (visita): confirma recebimento
            await whatsapp.send_text(phone, MSG_RECEBIDO)

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

        # 9. Gera PDFs em paralelo (relatório obrigatório, receituário só com recomendações)
        pdf_relatorio_bytes: bytes | None = None
        pdf_receituario_bytes: bytes | None = None
        numero_serie: str | None = None

        try:
            pdf_relatorio_bytes = await asyncio.to_thread(
                gerar_relatorio, agronomo, fazenda_db, talhao_db, dados, visita.data_visita
            )
            logger.info(f"Relatório PDF gerado — {len(pdf_relatorio_bytes)} bytes")

            if dados.recomendacoes:
                numero_serie = icp.gerar_numero_serie(visita.id)
                pdf_receituario_bytes = await asyncio.to_thread(
                    gerar_receituario,
                    agronomo,
                    fazenda_db,
                    talhao_db,
                    dados,
                    visita.data_visita,
                    numero_serie,
                )
                logger.info(f"Receituário PDF gerado — {len(pdf_receituario_bytes)} bytes")
        except Exception as e:
            logger.error(f"Erro ao gerar PDF da visita {visita.id}: {e}", exc_info=True)

        # 10. Upload dos PDFs para o Storage
        if pdf_relatorio_bytes:
            try:
                url_relatorio = await storage.upload_pdf(
                    path=f"visitas/{visita.id}/relatorio.pdf",
                    pdf_bytes=pdf_relatorio_bytes,
                )
                visita.pdf_relatorio_url = url_relatorio
            except Exception as e:
                logger.error(f"Erro no upload do relatório: {e}", exc_info=True)

        if pdf_receituario_bytes:
            try:
                url_receituario = await storage.upload_pdf(
                    path=f"visitas/{visita.id}/receituario.pdf",
                    pdf_bytes=pdf_receituario_bytes,
                )
                visita.pdf_receituario_url = url_receituario
            except Exception as e:
                logger.error(f"Erro no upload do receituário: {e}", exc_info=True)

        await db.commit()

        # 11. Envia resumo formatado ao agrônomo
        resumo = await ai_processor.gerar_resumo_whatsapp(
            dados=dados,
            nome_agronomo=agronomo.nome,
        )
        await whatsapp.send_text(phone, resumo)

        # 12. Envia PDFs via WhatsApp se foram enviados ao Storage
        if visita.pdf_relatorio_url:
            await whatsapp.send_document(
                phone,
                document_url=visita.pdf_relatorio_url,
                filename=f"relatorio_{visita.data_visita}.pdf",
            )

        if visita.pdf_receituario_url:
            await whatsapp.send_document(
                phone,
                document_url=visita.pdf_receituario_url,
                filename=f"receituario_{numero_serie}.pdf",
            )

        # 13. Marca como processada
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

        # Notifica fundador — falha silenciosa (não propaga)
        try:
            notificador = NotificacaoFundador(whatsapp)
            await notificador.erro_pipeline(
                agronomo_nome=_agronomo_nome,
                agronomo_phone=_agronomo_phone,
                erro=str(e),
                mensagem_id=str(mensagem_id),
            )
        except Exception:
            pass
