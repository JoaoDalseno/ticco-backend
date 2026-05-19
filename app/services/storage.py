"""
Upload de arquivos para o Supabase Storage.
"""
import asyncio
import logging
from functools import lru_cache

from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _supabase_client() -> Client:
    """Cliente Supabase cacheado — evita re-handshake a cada upload."""
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


class StorageService:
    """Gerencia uploads para o Supabase Storage."""

    def _upload_sync(self, path: str, pdf_bytes: bytes) -> str:
        """Executa o upload de forma síncrona (rodado via asyncio.to_thread)."""
        client = _supabase_client()
        bucket = settings.supabase_bucket

        try:
            client.storage.from_(bucket).remove([path])
        except Exception:
            pass  # Ignora se não existia

        client.storage.from_(bucket).upload(
            path=path,
            file=pdf_bytes,
            file_options={"content-type": "application/pdf", "upsert": "true"},
        )

        return client.storage.from_(bucket).get_public_url(path)

    async def upload_pdf(self, path: str, pdf_bytes: bytes) -> str:
        """
        Faz upload de um PDF para o bucket configurado.

        Args:
            path: Caminho dentro do bucket, ex: "visitas/uuid/relatorio.pdf"
            pdf_bytes: Conteúdo do PDF em bytes.

        Returns:
            URL pública do arquivo.
        """
        url = await asyncio.to_thread(self._upload_sync, path, pdf_bytes)
        logger.info("Upload concluído: %s", url)
        return url
