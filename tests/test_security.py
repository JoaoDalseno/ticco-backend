"""Testes da emissão/validação de JWT."""
import time
import uuid

import jwt
import pytest

from app.config import settings
from app.core.security import (
    TokenInvalidoError,
    criar_access_token,
    decodificar_access_token,
)


def test_token_emitido_e_decodificavel():
    agronomo_id = uuid.uuid4()
    token = criar_access_token(agronomo_id)
    assert decodificar_access_token(token) == agronomo_id


def test_token_assinatura_invalida_e_rejeitada():
    token = criar_access_token(uuid.uuid4())
    # Modifica último caractere — assinatura quebra
    adulterado = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(TokenInvalidoError):
        decodificar_access_token(adulterado)


def test_token_expirado_e_rejeitado():
    agronomo_id = uuid.uuid4()
    agora = int(time.time())
    payload = {"sub": str(agronomo_id), "iat": agora - 3600, "exp": agora - 1}
    expirado = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with pytest.raises(TokenInvalidoError):
        decodificar_access_token(expirado)


def test_token_com_secret_errado_e_rejeitado():
    agronomo_id = uuid.uuid4()
    fake = jwt.encode(
        {"sub": str(agronomo_id), "exp": int(time.time()) + 60},
        "secret-errado-secret-errado-secret",
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenInvalidoError):
        decodificar_access_token(fake)


def test_token_sem_sub_e_rejeitado():
    sem_sub = jwt.encode(
        {"exp": int(time.time()) + 60},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(TokenInvalidoError):
        decodificar_access_token(sem_sub)
