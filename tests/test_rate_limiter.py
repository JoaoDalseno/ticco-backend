"""
Testes para app/core/rate_limiter.py — sliding-window por telefone.
"""
import time

import pytest

from app.core.rate_limiter import (
    MAX_MESSAGES_PER_HOUR,
    MAX_MESSAGES_PER_MINUTE,
    _message_counts,
    _reset_counts,
    check_rate_limit,
)

PHONE = "+5516999990001"
PHONE2 = "+5511888880002"


@pytest.fixture(autouse=True)
def limpar_contadores():
    """Zera o estado global antes de cada teste."""
    _reset_counts()
    yield
    _reset_counts()


# ── Casos permitidos ──────────────────────────────────────────────────────────


def test_primeira_mensagem_permitida():
    allowed, motivo = check_rate_limit(PHONE)
    assert allowed is True
    assert motivo == ""


def test_mensagens_abaixo_do_limite_minuto():
    for _ in range(MAX_MESSAGES_PER_MINUTE - 1):
        allowed, _ = check_rate_limit(PHONE)
        assert allowed is True


def test_exatamente_no_limite_minuto_ainda_permitido():
    """A MAX_MESSAGES_PER_MINUTE-ésima mensagem ainda passa; a próxima não."""
    for _ in range(MAX_MESSAGES_PER_MINUTE):
        allowed, _ = check_rate_limit(PHONE)
        assert allowed is True

    # próxima deve ser bloqueada
    allowed, motivo = check_rate_limit(PHONE)
    assert allowed is False
    assert "minuto" in motivo


# ── Bloqueio por minuto ───────────────────────────────────────────────────────


def test_bloqueio_apos_limite_minuto():
    for _ in range(MAX_MESSAGES_PER_MINUTE):
        check_rate_limit(PHONE)

    allowed, motivo = check_rate_limit(PHONE)
    assert allowed is False
    assert "minuto" in motivo


def test_outros_numeros_nao_sao_afetados():
    """Rate limit é por telefone — outro número não deve ser bloqueado."""
    for _ in range(MAX_MESSAGES_PER_MINUTE):
        check_rate_limit(PHONE)

    # PHONE está bloqueado
    assert check_rate_limit(PHONE)[0] is False

    # PHONE2 deve estar livre
    allowed, _ = check_rate_limit(PHONE2)
    assert allowed is True


# ── Bloqueio por hora ─────────────────────────────────────────────────────────


def test_bloqueio_apos_limite_hora(monkeypatch):
    """Simula mensagens espalhadas em vários minutos até atingir o limite/hora."""
    now = time.monotonic()
    call_count = 0

    # Injeta timestamps artificiais: cada "minuto" tem MAX_MESSAGES_PER_MINUTE - 1 msgs
    # para não acionar o limite de minuto, mas acumular até o de hora.
    fake_times: list[float] = []
    batches = MAX_MESSAGES_PER_HOUR // (MAX_MESSAGES_PER_MINUTE - 1) + 1
    for batch in range(batches):
        for _ in range(MAX_MESSAGES_PER_MINUTE - 1):
            # Espalha em intervalos de 2 minutos (dentro da janela de 1 hora)
            fake_times.append(now - (batches - batch) * 120)

    # Preenche o estado interno diretamente
    _message_counts[PHONE] = fake_times[: MAX_MESSAGES_PER_HOUR - 1]

    # Ainda deve passar (está em MAX_MESSAGES_PER_HOUR - 1)
    allowed, _ = check_rate_limit(PHONE)
    assert allowed is True

    # Agora está em MAX_MESSAGES_PER_HOUR — próxima deve ser bloqueada
    allowed, motivo = check_rate_limit(PHONE)
    assert allowed is False
    assert "hora" in motivo


# ── Janela deslizante — expiração ─────────────────────────────────────────────


def test_timestamps_antigos_sao_descartados(monkeypatch):
    """Timestamps com mais de 1 hora são limpos; minuto expira em 60s."""
    now = time.monotonic()

    # Injeta timestamps com mais de 1 hora — devem ser ignorados
    _message_counts[PHONE] = [now - 3700] * MAX_MESSAGES_PER_HOUR

    # Todos os timestamps estão fora da janela → deve ser permitido
    allowed, _ = check_rate_limit(PHONE)
    assert allowed is True


def test_timestamps_do_minuto_anterior_nao_bloqueiam(monkeypatch):
    """Timestamps com mais de 60s atrás não contam para o limite de minuto."""
    now = time.monotonic()

    # 10 mensagens entre 61–120 segundos atrás (fora da janela de minuto)
    _message_counts[PHONE] = [now - 90] * 10

    # Não devem contar para o limite de minuto
    for _ in range(MAX_MESSAGES_PER_MINUTE):
        allowed, _ = check_rate_limit(PHONE)
        assert allowed is True
