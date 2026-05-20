"""
Rate limiting para o webhook WhatsApp.

Duas camadas:
  1. slowapi   — limite por IP (proteção na borda, via decorator)
  2. check_rate_limit — limite por telefone (janela deslizante em memória)

Limites por telefone:
  - 5 mensagens / minuto
  - 30 mensagens / hora

O bot NÃO responde quando bloqueado (evita loop de feedback).
"""
import logging
import time
from collections import defaultdict
from threading import Lock

from slowapi import Limiter
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

# ── slowapi — rate limit por IP ───────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)

# ── Sliding-window por telefone ───────────────────────────────────────────────

MAX_MESSAGES_PER_MINUTE: int = 5
MAX_MESSAGES_PER_HOUR: int = 30

# phone → lista de timestamps (float, epoch seconds)
_message_counts: dict[str, list[float]] = defaultdict(list)
_lock = Lock()


def check_rate_limit(phone: str) -> tuple[bool, str]:
    """
    Verifica e registra uma mensagem do número `phone`.

    Retorna:
        (True, "")           — mensagem permitida
        (False, motivo)      — mensagem bloqueada; `motivo` é human-readable

    Thread-safe via Lock (o worker roda em thread pool do asyncio).
    """
    now = time.monotonic()
    one_minute_ago = now - 60
    one_hour_ago = now - 3600

    with _lock:
        timestamps = _message_counts[phone]

        # Limpa timestamps mais antigos que 1 hora (janela máxima usada)
        _message_counts[phone] = [t for t in timestamps if t > one_hour_ago]
        timestamps = _message_counts[phone]

        count_last_minute = sum(1 for t in timestamps if t > one_minute_ago)
        count_last_hour = len(timestamps)

        if count_last_minute >= MAX_MESSAGES_PER_MINUTE:
            logger.warning(
                "Rate limit (minuto) atingido — phone=%s msgs_minuto=%d",
                _mask(phone),
                count_last_minute,
            )
            return False, f"limite de {MAX_MESSAGES_PER_MINUTE} mensagens/minuto atingido"

        if count_last_hour >= MAX_MESSAGES_PER_HOUR:
            logger.warning(
                "Rate limit (hora) atingido — phone=%s msgs_hora=%d",
                _mask(phone),
                count_last_hour,
            )
            return False, f"limite de {MAX_MESSAGES_PER_HOUR} mensagens/hora atingido"

        # Permitido — registra timestamp
        _message_counts[phone].append(now)
        return True, ""


def _mask(phone: str) -> str:
    """Mascara número para logs — evita PII (LGPD)."""
    return f"{phone[:3]}****{phone[-4:]}" if len(phone) > 7 else "***"


# ── Utilitário para testes ────────────────────────────────────────────────────

def _reset_counts() -> None:
    """Zera contadores — use apenas em testes."""
    with _lock:
        _message_counts.clear()
