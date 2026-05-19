"""
Parser de comandos de texto do WhatsApp.

Identifica se a mensagem do agrônomo é um comando curto
(ajuda, historico, fazendas, plano, status, saudação)
ou texto de visita real — que vai pro pipeline de IA.

Comandos são processados localmente, sem chamar Claude/Whisper.
"""
from enum import Enum


class Comando(Enum):
    AJUDA = "ajuda"
    HISTORICO = "historico"
    FAZENDAS = "fazendas"
    PLANO = "plano"
    STATUS = "status"
    SAUDACAO = "saudacao"
    VISITA = "visita"
    DESCONHECIDO = "desconhecido"


TRIGGERS: dict[Comando, list[str]] = {
    Comando.AJUDA: [
        "ajuda", "help", "?", "menu",
        "comandos", "o que voce faz",
        "o que você faz",
    ],
    Comando.HISTORICO: [
        "historico", "histórico",
        "ultimas visitas", "últimas visitas",
        "minhas visitas", "ver visitas",
    ],
    Comando.FAZENDAS: [
        "fazendas", "minhas fazendas",
        "ver fazendas", "lista fazendas",
        "listar fazendas",
    ],
    Comando.PLANO: [
        "plano", "meu plano",
        "assinatura", "minha assinatura",
        "quanto pago", "valor",
    ],
    Comando.STATUS: [
        "status", "minha conta",
        "conta", "informacoes",
        "informações",
    ],
    Comando.SAUDACAO: [
        "oi", "olá", "ola", "hey",
        "bom dia", "boa tarde", "boa noite",
        "ei", "eai", "e ai",
    ],
}


def identificar_comando(texto: str) -> Comando:
    """Mapeia o texto recebido para um Comando."""
    if not texto or not texto.strip():
        return Comando.DESCONHECIDO

    texto_limpo = texto.lower().strip()

    # Texto longo é visita real, não comando
    if len(texto_limpo) > 100:
        return Comando.VISITA

    # Tenta também com pontuação final removida ("boa tarde!", "ajuda.")
    # Não strippa "?" — ele próprio é um trigger de ajuda.
    sem_pontuacao = texto_limpo.rstrip("!.")
    candidatos = {texto_limpo, sem_pontuacao}

    for comando, triggers in TRIGGERS.items():
        for t in triggers:
            for cand in candidatos:
                if cand == t or cand.startswith(t + " "):
                    return comando

    if len(texto_limpo) < 50:
        return Comando.DESCONHECIDO

    return Comando.VISITA
