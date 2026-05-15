"""
Transcrição de áudio via Groq Whisper Large v3 Turbo (primário)
com fallback para OpenAI Whisper.
"""
import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_GROQ_MODEL = "whisper-large-v3-turbo"
_OPENAI_MODEL = "whisper-1"
_LANGUAGE = "pt"
_MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — limite da API Groq/OpenAI


def _validar_url_audio(url: str) -> None:
    """Previne SSRF: aceita apenas HTTPS para domínios públicos."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL de áudio deve usar HTTPS: {parsed.scheme!r}")
    host = parsed.hostname or ""
    # Bloqueia IPs privados e localhost
    blocked = ("localhost", "127.", "10.", "192.168.", "172.16.", "169.254.", "::1", "0.0.0.0")
    if any(host == b or host.startswith(b) for b in blocked):
        raise ValueError(f"URL de áudio aponta para host interno bloqueado: {host!r}")


async def _download_audio(url: str) -> bytes:
    """Baixa o áudio da URL retornada pela Z-API com proteção SSRF e limite de tamanho."""
    _validar_url_audio(url)
    async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        content_length = int(resp.headers.get("content-length", 0))
        if content_length > _MAX_AUDIO_BYTES:
            raise ValueError(f"Áudio muito grande: {content_length} bytes (max {_MAX_AUDIO_BYTES})")
        data = resp.content
        if len(data) > _MAX_AUDIO_BYTES:
            raise ValueError(f"Áudio excede limite de {_MAX_AUDIO_BYTES // (1024*1024)} MB")
        return data


async def _transcrever_groq(audio_bytes: bytes, filename: str) -> str:
    """Transcreve com Groq Whisper Large v3 Turbo."""
    from groq import AsyncGroq

    client = AsyncGroq(api_key=settings.groq_api_key)

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as audio_file:
            result = await client.audio.transcriptions.create(
                model=_GROQ_MODEL,
                file=(filename, audio_file, "audio/ogg"),
                language=_LANGUAGE,
                response_format="text",
            )
        return str(result).strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def _transcrever_openai(audio_bytes: bytes, filename: str) -> str:
    """Transcreve com OpenAI Whisper (fallback)."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    with tempfile.NamedTemporaryFile(suffix=Path(filename).suffix or ".ogg", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as audio_file:
            result = await client.audio.transcriptions.create(
                model=_OPENAI_MODEL,
                file=audio_file,
                language=_LANGUAGE,
            )
        return result.text.strip()
    finally:
        Path(tmp_path).unlink(missing_ok=True)


async def transcrever(midia_url: str, filename: str = "audio.ogg") -> str:
    """
    Baixa e transcreve o áudio.
    Tenta Groq primeiro; se falhar, usa OpenAI como fallback.
    """
    logger.info("Baixando áudio: %s", midia_url)
    audio_bytes = await _download_audio(midia_url)
    logger.info("Áudio baixado — %d bytes", len(audio_bytes))

    try:
        texto = await _transcrever_groq(audio_bytes, filename)
        logger.info("Transcrição Groq concluída (%d chars)", len(texto))
        return texto
    except Exception as exc:
        logger.warning("Groq falhou (%s) — tentando OpenAI fallback", exc)

    texto = await _transcrever_openai(audio_bytes, filename)
    logger.info("Transcrição OpenAI concluída (%d chars)", len(texto))
    return texto
