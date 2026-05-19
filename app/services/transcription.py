"""
Transcrição de áudio via Groq Whisper Large v3 Turbo (primário)
com fallback para OpenAI Whisper.
"""
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from groq import AsyncGroq

from app.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB — limite da API Groq/OpenAI


def validar_url_audio(url: str) -> None:
    """Previne SSRF: aceita apenas HTTPS para domínios públicos."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"URL de áudio deve usar HTTPS: {parsed.scheme!r}")
    host = parsed.hostname or ""
    blocked = ("localhost", "127.", "10.", "192.168.", "172.16.", "169.254.", "::1", "0.0.0.0")
    if any(host == b or host.startswith(b) for b in blocked):
        raise ValueError(f"URL de áudio aponta para host interno bloqueado: {host!r}")


class TranscriptionService:

    def __init__(self):
        self.client = AsyncGroq(api_key=settings.groq_api_key)
        self.fallback_enabled = bool(settings.openai_api_key)

    async def transcribe(
        self,
        audio_bytes: bytes,
        language: str = "pt",
        filename: str = "audio.ogg",
    ) -> str:
        """
        Transcreve áudio usando Groq Whisper (ultra rápido).
        Fallback pra OpenAI Whisper se Groq falhar.
        """
        try:
            return await self._transcribe_groq(audio_bytes, language, filename)
        except Exception as e:
            logger.warning(f"Groq falhou: {e}. Tentando OpenAI...")
            if self.fallback_enabled:
                return await self._transcribe_openai(audio_bytes, language, filename)
            raise

    async def _transcribe_groq(
        self,
        audio_bytes: bytes,
        language: str,
        filename: str,
    ) -> str:
        suffix = f".{filename.split('.')[-1]}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                transcript = await self.client.audio.transcriptions.create(
                    model="whisper-large-v3-turbo",
                    file=(filename, f),
                    language=language,
                    response_format="text",
                )
            result = str(transcript).strip()
            logger.info(f"Áudio transcrito via Groq: {len(result)} chars")
            return result
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    async def _transcribe_openai(
        self,
        audio_bytes: bytes,
        language: str,
        filename: str,
    ) -> str:
        import openai
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        suffix = f".{filename.split('.')[-1]}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        try:
            with open(tmp_path, "rb") as f:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=f,
                    language=language,
                    response_format="text",
                )
            result = transcript.text.strip()
            logger.info(f"Áudio transcrito via OpenAI: {len(result)} chars")
            return result
        finally:
            Path(tmp_path).unlink(missing_ok=True)
