"""
Testes de segurança — Validação de entrada.

Cobre TICCO-SEC-008 (FazendaBase extra=forbid) e validadores de telefone.
OWASP A03 — Injection

Para rodar: pytest tests/security/test_input_validation.py -v
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_agronomo, get_db
from app.config import settings
from app.main import app

_SECRET = settings.jwt_secret
_ALG = "HS256"


def _mock_agronomo() -> MagicMock:
    a = MagicMock()
    a.id = uuid.uuid4()
    a.plano = MagicMock()
    a.plano.value = "basico"
    return a


def _mock_db() -> AsyncMock:
    db = AsyncMock()
    db.execute = AsyncMock(return_value=AsyncMock(scalar_one=lambda: 0))
    return db


def _make_token() -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        _SECRET,
        algorithm=_ALG,
    )


@pytest.fixture(autouse=True)
def override_deps():
    """Override FastAPI dependencies para evitar DB real nos testes de validação."""
    agronomo = _mock_agronomo()
    app.dependency_overrides[get_current_agronomo] = lambda: agronomo
    app.dependency_overrides[get_db] = lambda: AsyncMock()
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {_make_token()}"}


# ============================================================
# FazendaBase extra="forbid" (TICCO-SEC-008, Medium)
# ============================================================

@pytest.mark.asyncio
async def test_fazenda_rejeita_campo_extra(client, auth_headers):
    """Campos não declarados no schema → 422. A03."""
    payload = {
        "nome": "Fazenda Boa",
        "dono_nome": "João Silva",
        "cidade": "Franca",
        "estado": "SP",
        "area_total_ha": 100.0,
        "campo_malicioso": "injection_attempt",
    }
    r = await client.post("/v1/fazendas", json=payload, headers=auth_headers)
    assert r.status_code == 422, (
        f"Campo extra deveria ser rejeitado (422), recebido {r.status_code}: {r.text}"
    )


@pytest.mark.asyncio
async def test_fazenda_rejeita_telefone_invalido(client, auth_headers):
    """Telefone fora do padrão E.164 (+55 + 10-11 dígitos) → 422. A03."""
    payload = {
        "nome": "Fazenda Boa",
        "dono_nome": "João Silva",
        "dono_wpp": "99999999",  # inválido — curto demais e sem +55
        "cidade": "Franca",
        "estado": "SP",
        "area_total_ha": 100.0,
    }
    r = await client.post("/v1/fazendas", json=payload, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fazenda_rejeita_telefone_sem_codigo_pais(client, auth_headers):
    """Telefone sem +55 → 422. A03."""
    payload = {
        "nome": "Fazenda Boa",
        "dono_nome": "João Silva",
        "dono_wpp": "16999999999",  # sem +55
        "cidade": "Franca",
        "estado": "SP",
        "area_total_ha": 100.0,
    }
    r = await client.post("/v1/fazendas", json=payload, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fazenda_area_negativa_rejeitada(client, auth_headers):
    """área_total_ha negativa → 422 (gt=0). A03."""
    payload = {
        "nome": "Fazenda Boa",
        "dono_nome": "João Silva",
        "cidade": "Franca",
        "estado": "SP",
        "area_total_ha": -1.0,  # inválido
    }
    r = await client.post("/v1/fazendas", json=payload, headers=auth_headers)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fazenda_nome_muito_curto_rejeitado(client, auth_headers):
    """nome < 2 chars → 422 (min_length=2). A03."""
    payload = {
        "nome": "X",  # muito curto
        "dono_nome": "João Silva",
        "cidade": "Franca",
        "estado": "SP",
        "area_total_ha": 100.0,
    }
    r = await client.post("/v1/fazendas", json=payload, headers=auth_headers)
    assert r.status_code == 422
