"""
Worker de processamento de mensagens — pipeline completo (Fases 3-5).

Fluxo:
  1. Carrega mensagem + agrônomo + fazendas/talhões
  2. Transcrição de áudio (Groq → OpenAI fallback)
  3. Claude estrutura o relato → VisitaDadosEstruturados
  4. Resolve fazenda/talhão por fuzzy match
  5. Cria Visita no banco
  6. Gera PDF do relatório → upload Supabase Storage
  7. Se há produtos → gera receituário → cria Receituario no banco
  8. Salva URLs dos PDFs na Visita
  9. Envia confirmação ao agrônomo
 10. Se dono tem módulo ativo → envia relatório ao dono da fazenda
"""
import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.mensagem import Mensagem, TipoEnum
from app.models.receituario import Receituario, StatusReceituarioEnum
from app.models.talhao import Talhao
from app.models.visita import StatusVisitaEnum, Visita
from app.schemas.visita import VisitaDadosEstruturados
from app.services import ai_processor, pdf_generator, storage, transcription
from app.services.whatsapp import zapi

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fuzzy_match(nome_claude: str | None, nomes: list[str]) -> str | None:
    if not nome_claude:
        return None
    nl = nome_claude.lower()
    for nome in nomes:
        if nl in nome.lower() or nome.lower() in nl:
            return nome
    return None


def _resolver_fazenda(dados: VisitaDadosEstruturados, fazendas: list[Fazenda]) -> Fazenda | None:
    match = _fuzzy_match(dados.fazenda_identificada, [f.nome for f in fazendas])
    return next((f for f in fazendas if f.nome == match), None) if match else None


def _resolver_talhao(dados: VisitaDadosEstruturados, fazenda: Fazenda | None) -> Talhao | None:
    if not fazenda:
        return None
    match = _fuzzy_match(dados.talhao_identificado, [t.nome for t in fazenda.talhoes])
    return next((t for t in fazenda.talhoes if t.nome == match), None) if match else None


def _data_visita(dados: VisitaDadosEstruturados) -> date:
    if dados.data_visita:
        try:
            return date.fromisoformat(dados.data_visita)
        except ValueError:
            pass
    return date.today()


def _numero_serie() -> str:
    ano = datetime.now(timezone.utc).year
    uid = uuid.uuid4().hex[:6].upper()
    return f"TICCO-{ano}-{uid}"


def _msg_confirmacao(
    dados: VisitaDadosEstruturados,
    fazenda: Fazenda,
    talhao: Talhao | None,
    relatorio_url: str | None,
) -> str:
    linhas = ["✅ *Visita registrada com sucesso!*\n"]
    linhas.append(f"🌿 Fazenda: *{fazenda.nome}*")
    if talhao:
        linhas.append(f"📍 Talhão: *{talhao.nome}*")
    if dados.doencas:
        linhas.append(f"\n🦠 Doenças: {', '.join(d.nome for d in dados.doencas)}")
    if dados.pragas:
        linhas.append(f"🐛 Pragas: {', '.join(p.nome for p in dados.pragas)}")
    if dados.recomendacoes:
        linhas.append(f"\n💊 Recomendações: {len(dados.recomendacoes)}")
    if dados.produtos_receituario:
        linhas.append(f"📋 Receituário gerado: {len(dados.produtos_receituario)} produto(s)")
    if dados.proxima_visita:
        linhas.append(f"\n📅 Próxima visita: *{dados.proxima_visita}*")
    if relatorio_url:
        linhas.append(f"\n📄 Relatório: {relatorio_url}")
    return "\n".join(linhas)


def _msg_dono(agronomo: Agronomo, fazenda: Fazenda, dados: VisitaDadosEstruturados, relatorio_url: str | None) -> str:
    linhas = [
        f"Olá, *{fazenda.dono_nome}*! 👋",
        f"\nSeu agrônomo *{agronomo.nome}* realizou uma visita técnica na *{fazenda.nome}*.\n",
    ]
    if dados.doencas:
        linhas.append(f"🦠 Doenças identificadas: {', '.join(d.nome for d in dados.doencas)}")
    if dados.pragas:
        linhas.append(f"🐛 Pragas identificadas: {', '.join(p.nome for p in dados.pragas)}")
    if dados.recomendacoes:
        linhas.append(f"💊 {len(dados.recomendacoes)} recomendação(ões) técnica(s) emitida(s)")
    if relatorio_url:
        linhas.append(f"\n📄 Relatório completo: {relatorio_url}")
    return "\n".join(linhas)


# ── Pipeline principal ────────────────────────────────────────────────────────

async def process_message(mensagem_id: uuid.UUID, db: AsyncSession) -> None:
    # ── 1. Carrega dados ──────────────────────────────────────────────────────
    result = await db.execute(select(Mensagem).where(Mensagem.id == mensagem_id))
    mensagem = result.scalar_one_or_none()
    if not mensagem or not mensagem.agronomo_id:
        logger.error("Mensagem não encontrada ou sem agrônomo: %s", mensagem_id)
        return

    agronomo_result = await db.execute(
        select(Agronomo)
        .where(Agronomo.id == mensagem.agronomo_id)
        .options(selectinload(Agronomo.fazendas).selectinload(Fazenda.talhoes))
    )
    agronomo = agronomo_result.scalar_one_or_none()
    if not agronomo:
        logger.error("Agrônomo não encontrado: %s", mensagem.agronomo_id)
        return

    logger.info("Processando mensagem %s — agrônomo: %s", mensagem_id, agronomo.nome)

    # ── 2. Transcrição ────────────────────────────────────────────────────────
    texto: str | None = mensagem.conteudo_texto

    if mensagem.tipo == TipoEnum.audio and mensagem.midia_url:
        try:
            texto = await transcription.transcrever(mensagem.midia_url)
            mensagem.transcricao = texto
            await db.flush()
        except Exception:
            logger.exception("Falha na transcrição — mensagem %s", mensagem_id)
            await _marcar_erro(mensagem, db)
            await zapi.send_text(
                agronomo.telefone_wpp,
                "⚠️ Não consegui transcrever seu áudio. Tente enviar como texto.",
            )
            return

    if not texto:
        logger.warning("Mensagem %s sem conteúdo", mensagem_id)
        return

    # ── 3. Claude estrutura ───────────────────────────────────────────────────
    try:
        dados = await ai_processor.processar_relato(texto, agronomo, agronomo.fazendas)
    except Exception:
        logger.exception("Falha no Claude — mensagem %s", mensagem_id)
        await _marcar_erro(mensagem, db)
        await zapi.send_text(
            agronomo.telefone_wpp,
            "⚠️ Erro ao processar seu relato. Tente novamente em instantes.",
        )
        return

    # ── 4. Resolve fazenda/talhão ─────────────────────────────────────────────
    fazenda = _resolver_fazenda(dados, agronomo.fazendas) or (
        agronomo.fazendas[0] if agronomo.fazendas else None
    )
    if not fazenda:
        await zapi.send_text(
            agronomo.telefone_wpp,
            "⚠️ Nenhuma fazenda cadastrada. Cadastre uma fazenda antes de registrar visitas.",
        )
        return

    talhao = _resolver_talhao(dados, fazenda)
    data_vis = _data_visita(dados)

    # ── 5. Cria Visita ────────────────────────────────────────────────────────
    visita = Visita(
        id=uuid.uuid4(),
        agronomo_id=agronomo.id,
        fazenda_id=fazenda.id,
        talhao_id=talhao.id if talhao else None,
        mensagem_id=mensagem.id,
        data_visita=data_vis,
        texto_bruto=texto,
        dados_estruturados=dados.model_dump(),
        status=StatusVisitaEnum.processando,
    )
    db.add(visita)
    mensagem.processada = True
    await db.flush()

    # ── 6. PDF Relatório ──────────────────────────────────────────────────────
    relatorio_url: str | None = None
    try:
        pdf_bytes = pdf_generator.gerar_relatorio(agronomo, fazenda, talhao, dados, data_vis)
        path = f"visitas/{visita.id}/relatorio.pdf"
        relatorio_url = await storage.upload_pdf(path, pdf_bytes)
        visita.pdf_relatorio_url = relatorio_url
        logger.info("PDF relatório gerado: %s", relatorio_url)
    except Exception:
        logger.exception("Falha ao gerar PDF relatório — visita %s", visita.id)

    # ── 7. Receituário (se houver produtos) ───────────────────────────────────
    receituario_url: str | None = None
    if dados.produtos_receituario:
        try:
            num_serie = _numero_serie()
            rec_bytes = pdf_generator.gerar_receituario(
                agronomo, fazenda, talhao, dados, data_vis, num_serie
            )
            rec_path = f"visitas/{visita.id}/receituario.pdf"
            receituario_url = await storage.upload_pdf(rec_path, rec_bytes)
            visita.pdf_receituario_url = receituario_url

            receituario = Receituario(
                id=uuid.uuid4(),
                visita_id=visita.id,
                numero_serie=num_serie,
                produtos=[p.model_dump() for p in dados.produtos_receituario],
                pdf_assinado_url=receituario_url,
                status=StatusReceituarioEnum.assinado,
            )
            db.add(receituario)
            logger.info("Receituário gerado: %s — %s", num_serie, receituario_url)
        except Exception:
            logger.exception("Falha ao gerar receituário — visita %s", visita.id)

    # ── 8. Finaliza visita ────────────────────────────────────────────────────
    visita.status = StatusVisitaEnum.completa
    await db.commit()

    # ── 9. Notifica agrônomo ──────────────────────────────────────────────────
    await zapi.send_text(
        agronomo.telefone_wpp,
        _msg_confirmacao(dados, fazenda, talhao, relatorio_url),
    )
    if relatorio_url:
        try:
            await zapi.send_document(agronomo.telefone_wpp, relatorio_url, "relatorio_visita.pdf")
        except Exception:
            logger.warning("Falha ao enviar PDF ao agrônomo via WhatsApp")

    if receituario_url:
        try:
            await zapi.send_document(agronomo.telefone_wpp, receituario_url, "receituario.pdf")
        except Exception:
            logger.warning("Falha ao enviar receituário ao agrônomo via WhatsApp")

    # ── 10. Notifica dono (se módulo ativo) ───────────────────────────────────
    if fazenda.modulo_dono_ativo and fazenda.dono_wpp and relatorio_url:
        try:
            await zapi.send_text(fazenda.dono_wpp, _msg_dono(agronomo, fazenda, dados, relatorio_url))
            await zapi.send_document(fazenda.dono_wpp, relatorio_url, "relatorio_visita.pdf")
            visita.enviado_para_dono = True
            await db.commit()
            logger.info("Relatório enviado ao dono: %s", fazenda.dono_wpp)
        except Exception:
            logger.exception("Falha ao notificar dono — fazenda %s", fazenda.id)


async def _marcar_erro(mensagem: Mensagem, db: AsyncSession) -> None:
    mensagem.processada = True
    await db.commit()
