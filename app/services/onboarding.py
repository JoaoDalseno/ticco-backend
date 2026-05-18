"""
Onboarding conversacional via WhatsApp.

Máquina de estados simples: guia o novo agrônomo pelo cadastro completo
em 5 perguntas. Estado mantido em memória (dict) — suficiente para
validação. Migrar para Redis quando escalar.

Fluxo:
  aguarda_confirmacao → aguarda_nome → aguarda_crea
    → aguarda_cidade → aguarda_cpf → concluido
"""
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.agronomo import Agronomo, PlanoEnum, StatusPagamentoEnum

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────

SESSION_TTL_MINUTES = 30

STEPS = [
    "aguarda_confirmacao",
    "aguarda_nome",
    "aguarda_crea",
    "aguarda_cidade",
    "aguarda_cpf",
    "concluido",
]

MSGS: dict[str, str] = {
    "boas_vindas": (
        "Salve! Aqui é o Ticco 🐦\n\n"
        "Sou o assistente de agrônomos cafeicultores "
        "da Mogiana.\n\n"
        "Você é agrônomo consultor de café?\n"
        "Responde *sim* pra eu te cadastrar rapidinho."
    ),
    "pede_nome": (
        "Boa! Vamos lá 🌱\n\n"
        "Me passa seu *nome completo*:"
    ),
    "pede_crea": (
        "Me passa seu número do *CREA*\n"
        "_(ex: SP-123456/D ou MG-123456/D)_:"
    ),
    "pede_cidade": (
        "Qual *cidade* você atua principalmente?\n"
        "_(ex: Pedregulho, Franca, Patrocínio...)_"
    ),
    "pede_cpf": (
        "Último passo! Me passa seu *CPF*\n"
        "_(só os números, ex: 12345678900)_:"
    ),
    "concluido": (
        "Cadastro feito! 🎉\n\n"
        "Bem-vindo ao Ticco, *{nome}*!\n\n"
        "Você tem *14 dias grátis* pra testar tudo.\n\n"
        "Pra começar: termina uma visita técnica, "
        "abre esse zap e manda um áudio descrevendo "
        "o que você viu. Eu cuido do resto. 🐦\n\n"
        "_Qualquer dúvida chama o João diretamente._"
    ),
    "nao_entendi": (
        "Não entendi 😅\n"
        "Responde *sim* pra eu te cadastrar, "
        "ou *não* pra encerrar."
    ),
    "cancelado": (
        "Tudo bem! Se mudar de ideia é só mandar "
        "mensagem aqui. 🐦"
    ),
}


# ── Validações ────────────────────────────────────────────────────────────────

def validar_crea(crea: str) -> bool:
    """Aceita qualquer CREA com pelo menos 5 caracteres (letras + números)."""
    return len(crea.strip()) >= 5


def validar_cpf(cpf: str) -> bool:
    """Valida se tem 11 dígitos numéricos (não valida dígito verificador por ora)."""
    numeros = re.sub(r"\D", "", cpf)
    return len(numeros) == 11


def formatar_cpf(cpf: str) -> str:
    """Formata CPF: 12345678900 → 123.456.789-00"""
    n = re.sub(r"\D", "", cpf)
    return f"{n[:3]}.{n[3:6]}.{n[6:9]}-{n[9:]}"


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


# ── Serviço de estado ─────────────────────────────────────────────────────────

class OnboardingService:
    """
    Gerencia sessões de onboarding em memória.
    Thread-safe para workers assíncronos (GIL do CPython garante).
    """

    def __init__(self) -> None:
        # { phone: {"step": str, "dados": dict, "expires_at": datetime} }
        self._sessions: dict[str, dict] = {}

    def is_in_onboarding(self, phone: str) -> bool:
        """Verifica se número está em processo de onboarding (e não expirou)."""
        self._cleanup_expired()
        return phone in self._sessions

    def get_step(self, phone: str) -> Optional[str]:
        """Retorna o step atual do número."""
        session = self._sessions.get(phone)
        return session["step"] if session else None

    def start_onboarding(self, phone: str) -> None:
        """Inicia sessão de onboarding pro número, sempre do step inicial."""
        self._cleanup_expired()
        self._sessions[phone] = {
            "step": "aguarda_confirmacao",
            "dados": {},
            "expires_at": datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES),
        }
        logger.info("Onboarding iniciado: %s", _mask(phone))

    def get_dados(self, phone: str) -> dict:
        """Retorna dados coletados até agora."""
        session = self._sessions.get(phone)
        return session["dados"].copy() if session else {}

    def set_dado(self, phone: str, campo: str, valor: str) -> None:
        """Salva um dado coletado e renova o TTL da sessão."""
        session = self._sessions.get(phone)
        if session:
            session["dados"][campo] = valor
            session["expires_at"] = datetime.now(timezone.utc) + timedelta(minutes=SESSION_TTL_MINUTES)

    def advance_step(self, phone: str) -> str:
        """Avança pro próximo step e retorna qual é."""
        session = self._sessions.get(phone)
        if not session:
            return "aguarda_confirmacao"
        atual = session["step"]
        try:
            idx = STEPS.index(atual)
            proximo = STEPS[idx + 1] if idx + 1 < len(STEPS) else "concluido"
        except ValueError:
            proximo = "concluido"
        session["step"] = proximo
        return proximo

    def clear_session(self, phone: str) -> None:
        """Limpa sessão (após concluir ou cancelar)."""
        self._sessions.pop(phone, None)
        logger.info("Onboarding encerrado: %s", _mask(phone))

    def _cleanup_expired(self) -> None:
        """Remove sessões expiradas. Chamado a cada is_in_onboarding."""
        agora = datetime.now(timezone.utc)
        expirados = [
            p for p, s in self._sessions.items()
            if agora > s["expires_at"]
        ]
        for p in expirados:
            del self._sessions[p]
            logger.debug("Sessão de onboarding expirada: %s", _mask(p))


# ── Lógica de cada step ───────────────────────────────────────────────────────

async def handle_onboarding_step(
    phone: str,
    texto: str,
    db: AsyncSession,
    whatsapp,  # ZAPIWhatsAppService — sem import circular
    onboarding: OnboardingService,
) -> None:
    """Processa a resposta do usuário para o step atual da sessão."""
    step = onboarding.get_step(phone)
    texto = (texto or "").strip()
    texto_lower = texto.lower()

    if step == "aguarda_confirmacao":
        if any(w in texto_lower for w in ["sim", "s", "yes", "quero", "pode", "claro"]):
            onboarding.advance_step(phone)
            await whatsapp.send_text(phone, MSGS["pede_nome"])

        elif any(w in texto_lower for w in ["nao", "não", "no", "nope", "nã"]):
            onboarding.clear_session(phone)
            await whatsapp.send_text(phone, MSGS["cancelado"])

        else:
            await whatsapp.send_text(phone, MSGS["nao_entendi"])

    elif step == "aguarda_nome":
        if len(texto) >= 3:
            onboarding.set_dado(phone, "nome", texto.title())
            onboarding.advance_step(phone)
            await whatsapp.send_text(phone, MSGS["pede_crea"])
        else:
            await whatsapp.send_text(phone, "Nome muito curto. Me passa seu nome completo:")

    elif step == "aguarda_crea":
        if validar_crea(texto):
            onboarding.set_dado(phone, "crea", texto.upper())
            onboarding.advance_step(phone)
            await whatsapp.send_text(phone, MSGS["pede_cidade"])
        else:
            await whatsapp.send_text(phone, "Formato inválido. Tenta assim: SP-123456/D")

    elif step == "aguarda_cidade":
        if len(texto) >= 3:
            onboarding.set_dado(phone, "cidade", texto.title())
            onboarding.advance_step(phone)
            await whatsapp.send_text(phone, MSGS["pede_cpf"])
        else:
            await whatsapp.send_text(phone, "Me passa o nome da cidade:")

    elif step == "aguarda_cpf":
        if validar_cpf(texto):
            cpf_formatado = formatar_cpf(texto)
            onboarding.set_dado(phone, "cpf", cpf_formatado)

            dados = onboarding.get_dados(phone)
            try:
                await _criar_agronomo_via_onboarding(phone=phone, dados=dados, db=db)
            except Exception as e:
                logger.error("Erro ao criar agrônomo %s: %s", _mask(phone), e, exc_info=True)
                await whatsapp.send_text(
                    phone,
                    "Tive um problema ao finalizar o cadastro 😅\n"
                    "Tenta de novo daqui a pouco ou chama o João.",
                )
                return

            onboarding.clear_session(phone)

            msg_final = MSGS["concluido"].format(nome=dados["nome"])
            await whatsapp.send_text(phone, msg_final)

            # Notifica fundador sobre novo cadastro
            if settings.founder_phone:
                await whatsapp.send_text(
                    settings.founder_phone,
                    f"🐦 *Novo agrônomo cadastrado!*\n\n"
                    f"Nome: {dados['nome']}\n"
                    f"CREA: {dados['crea']}\n"
                    f"Cidade: {dados['cidade']}\n"
                    f"Tel: {phone}",
                )
        else:
            await whatsapp.send_text(
                phone,
                "CPF inválido. Me passa só os 11 números, sem pontos ou traço:",
            )

    else:
        # Step desconhecido — reinicia o fluxo
        logger.warning("Step desconhecido '%s' para %s — reiniciando", step, _mask(phone))
        onboarding.clear_session(phone)
        onboarding.start_onboarding(phone)
        await whatsapp.send_text(phone, MSGS["boas_vindas"])


async def _criar_agronomo_via_onboarding(
    phone: str,
    dados: dict,
    db: AsyncSession,
) -> Agronomo:
    """Persiste o novo agrônomo no banco com trial de 14 dias."""
    agronomo = Agronomo(
        id=uuid.uuid4(),
        nome=dados["nome"],
        cpf=dados["cpf"],
        crea=dados["crea"],
        telefone_wpp=phone,
        plano=PlanoEnum.basico,
        status_pagamento=StatusPagamentoEnum.trial,
        trial_ate=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(agronomo)
    await db.commit()
    await db.refresh(agronomo)
    logger.info("Agrônomo criado via onboarding: %s (%s)", agronomo.nome, _mask(phone))
    return agronomo
