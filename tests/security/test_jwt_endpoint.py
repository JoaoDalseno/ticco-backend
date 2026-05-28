"""
Testes de segurança — JWT via endpoints HTTP.

Cobre TICCO-SEC-007 (iat obrigatório) e ataques clássicos de JWT.
OWASP A07 — Identification and Authentication Failures
OWASP A02 — Cryptographic Failures

Para rodar: pytest tests/security/test_jwt_endpoint.py -v
"""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app

_SECRET = settings.jwt_secret
_ALG = "HS256"
_PROTECTED = "/v1/fazendas"  # endpoint protegido por JWT (POST)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _token(**overrides) -> str:
    """Gera JWT válido e aplica overrides ao payload."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    payload.update(overrides)
    return jwt.encode(payload, _SECRET, algorithm=_ALG)


@pytest.mark.asyncio
async def test_jwt_rejeita_alg_none(client):
    """Token com alg:none não deve ser aceito. A07."""
    try:
        now = datetime.now(timezone.utc)
        token = jwt.encode(
            {"sub": str(uuid.uuid4()), "exp": int((now + timedelta(hours=1)).timestamp())},
            "",
            algorithm="none",
        )
    except Exception:
        pytest.skip("PyJWT recusou gerar token alg:none — comportamento seguro")

    r = await client.post(_PROTECTED, json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_rejeita_assinatura_invalida(client):
    """Token assinado com segredo errado → 401. A02."""
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        "segredo-completamente-errado-xyz",
        algorithm=_ALG,
    )
    r = await client.post(_PROTECTED, json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_rejeita_token_expirado(client):
    """Token expirado há 1 hora → 401. A07."""
    expired = datetime.now(timezone.utc) - timedelta(hours=1)
    token = _token(
        exp=int(expired.timestamp()),
        iat=int((expired - timedelta(hours=1)).timestamp()),
    )
    r = await client.post(_PROTECTED, json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_rejeita_sem_iat(client):
    """Token sem campo iat → 401 (TICCO-SEC-007). A07."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        # sem "iat" propositalmente
    }
    token = jwt.encode(payload, _SECRET, algorithm=_ALG)
    r = await client.post(_PROTECTED, json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_rejeita_sem_authorization_header(client):
    """Request sem header Authorization → 401/403. A07."""
    r = await client.post(_PROTECTED, json={})
    assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_jwt_rejeita_token_adulterado(client):
    """Modifica último char da assinatura → 401. A02."""
    token = _token()
    adulterado = token[:-1] + ("A" if token[-1] != "A" else "B")
    r = await client.post(_PROTECTED, json={}, headers={"Authorization": f"Bearer {adulterado}"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_jwt_rejeita_bearer_invalido(client):
    """Token mal-formado → 401/403/422. A07."""
    r = await client.post(_PROTECTED, json={}, headers={"Authorization": "Bearer not.a.valid.jwt.token"})
    assert r.status_code in (401, 403, 422)
