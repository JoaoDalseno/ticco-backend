"""
Fluxo de onboarding via WhatsApp.

Estado mantido em memória (dict global). Cada número passa pelas etapas:
  NOME → CPF → CREA → EMAIL (opcional) → CRIADO

Limitação: reinicia se o servidor reiniciar. Para produção, persistir no DB.
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agronomo import Agronomo, PlanoEnum, StatusPagamentoEnum
from app.services.notificacao_fundador import NotificacaoFundador
from app.services.whatsapp import zapi
from app.services.whatsapp.zapi import ZAPIWhatsAppService

_whatsapp_svc = ZAPIWhatsAppService()

logger = logging.getLogger(__name__)

_ONBOARDING_TTL = timedelta(minutes=30)


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


# ── Estado em memória ─────────────────────────────────────────────────────────

class Etapa(str, Enum):
    NOME = "nome"
    CPF = "cpf"
    CREA = "crea"
    EMAIL = "email"


_estados: dict[str, dict] = {}
# Formato: { phone: {"etapa": Etapa, "dados": {...}, "iniciado_em": datetime} }


def _limpar_expirados() -> None:
    """Remove estados de onboarding abandonados (TTL 30 min)."""
    agora = datetime.now(timezone.utc)
    expirados = [
        p for p, s in _estados.items()
        if agora - s.get("iniciado_em", agora) > _ONBOARDING_TTL
    ]
    for p in expirados:
        del _estados[p]
        logger.debug("Onboarding expirado removido: %s", _mask(p))


# ── Helpers de validação ──────────────────────────────────────────────────────

def _so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor)


def _cpf_valido(cpf: str) -> bool:
    """Valida CPF com dígitos verificadores (algoritmo oficial)."""
    cpf = _so_digitos(cpf)
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    # Primeiro dígito verificador
    soma = sum(int(cpf[i]) * (10 - i) for i in range(9))
    d1 = (soma * 10 % 11) % 10
    if d1 != int(cpf[9]):
        return False
    # Segundo dígito verificador
    soma = sum(int(cpf[i]) * (11 - i) for i in range(10))
    d2 = (soma * 10 % 11) % 10
    return d2 == int(cpf[10])


def _crea_valido(crea: str) -> bool:
    return len(crea.strip()) >= 4


# ── Mensagens ────────────────────────────────────────────────────────────────

BOAS_VINDAS = (
    "Olá! 👋 Seja bem-vindo ao *Ticco* — seu assistente de consultoria cafeicultora.\n\n"
    "Seu número ainda não está cadastrado. Vamos criar sua conta agora?\n\n"
    "Por favor, me informe seu *nome completo*:"
)

PEDE_CPF = "Ótimo! Agora informe seu *CPF* (apenas números):"

PEDE_CREA = "Perfeito! Informe seu número de *CREA* (ex: SP-123456/D):"

PEDE_EMAIL = (
    "Quase lá! Informe seu *e-mail* (opcional — pode digitar \"pular\" para ignorar):"
)

def _msg_boas_vindas_final(nome: str) -> str:
    return (
        f"✅ Cadastro concluído! Bem-vindo, *{nome}*!\n\n"
        "Você está no plano *trial* por 14 dias.\n\n"
        "Para registrar uma visita técnica, basta me enviar um áudio ou texto "
        "descrevendo o que observou na lavoura. Pode começar! ☕\n\n"
        f"_Dúvidas? {settings.contact_email}_"
    )

MSG_CPF_INVALIDO = "CPF inválido. Por favor, informe os 11 dígitos do seu CPF:"
MSG_CREA_INVALIDO = "CREA inválido. Informe no formato SP-123456/D ou similar:"
MSG_PEDE_TEXTO = (
    "Pra finalizar seu cadastro, por favor *escreva como texto*. "
    "Ainda não consigo entender áudios nessa etapa. 🙏"
)


# ── Lógica principal ─────────────────────────────────────────────────────────

async def iniciar(phone: str) -> None:
    """Inicia o onboarding para um número novo."""
    _limpar_expirados()
    _estados[phone] = {"etapa": Etapa.NOME, "dados": {}, "iniciado_em": datetime.now(timezone.utc)}
    await zapi.send_text(phone, BOAS_VINDAS)


async def processar_resposta(phone: str, texto: str | None, db: AsyncSession) -> None:
    """Processa a resposta do usuário na etapa atual do onboarding."""
    estado = _estados.get(phone)
    if not estado:
        await iniciar(phone)
        return

    etapa = estado["etapa"]
    dados = estado["dados"]
    texto = (texto or "").strip()

    # Sem texto (ex: áudio durante onboarding) — orienta a escrever
    if not texto:
        await zapi.send_text(phone, MSG_PEDE_TEXTO)
        return

    if etapa == Etapa.NOME:
        if len(texto) < 3:
            await zapi.send_text(phone, "Por favor, informe seu nome completo:")
            return
        dados["nome"] = texto
        estado["etapa"] = Etapa.CPF
        await zapi.send_text(phone, PEDE_CPF)

    elif etapa == Etapa.CPF:
        cpf = _so_digitos(texto)
        if not _cpf_valido(cpf):
            await zapi.send_text(phone, MSG_CPF_INVALIDO)
            return
        dados["cpf"] = cpf
        estado["etapa"] = Etapa.CREA
        await zapi.send_text(phone, PEDE_CREA)

    elif etapa == Etapa.CREA:
        if not _crea_valido(texto):
            await zapi.send_text(phone, MSG_CREA_INVALIDO)
            return
        dados["crea"] = texto.strip()
        estado["etapa"] = Etapa.EMAIL
        await zapi.send_text(phone, PEDE_EMAIL)

    elif etapa == Etapa.EMAIL:
        email = None if texto.lower() in {"pular", "nao", "não", "-"} else texto
        dados["email"] = email
        await _criar_agronomo(phone, dados, db)
        del _estados[phone]


async def _criar_agronomo(phone: str, dados: dict, db: AsyncSession) -> None:
    """Persiste o novo agrônomo no banco e envia confirmação."""
    try:
        agronomo = Agronomo(
            id=uuid.uuid4(),
            nome=dados["nome"],
            cpf=dados["cpf"],
            crea=dados["crea"],
            telefone_wpp=phone,
            email=dados.get("email"),
            plano=PlanoEnum.free,
            status_pagamento=StatusPagamentoEnum.trial,
            trial_ate=datetime.now(timezone.utc) + timedelta(days=14),
        )
        db.add(agronomo)
        await db.commit()
        logger.info("Novo agrônomo criado via onboarding: %s (%s)", agronomo.nome, _mask(phone))
        await zapi.send_text(phone, _msg_boas_vindas_final(agronomo.nome))

        # Notifica fundador — cidade não é coletada no onboarding; usa fallback
        try:
            notificador = NotificacaoFundador(_whatsapp_svc)
            await notificador.novo_cadastro(
                nome=agronomo.nome,
                crea=agronomo.crea,
                cidade=dados.get("cidade", "—"),
                phone=phone,
            )
        except Exception:
            logger.debug("Falha ao notificar fundador sobre novo cadastro (não crítico)")
    except Exception:
        await db.rollback()
        logger.exception("Erro ao criar agrônomo via onboarding: %s", _mask(phone))
        await zapi.send_text(
            phone,
            "Ocorreu um erro ao finalizar seu cadastro. Tente novamente em instantes."
        )


def em_onboarding(phone: str) -> bool:
    return phone in _estados
