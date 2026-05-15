"""
Upload de arquivos para o Supabase Storage.
"""
import logging

from supabase import create_client

from app.config import settings

logger = logging.getLogger(__name__)


def _client():
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def upload_pdf(path: str, pdf_bytes: bytes) -> str:
    """
    Faz upload de um PDF para o bucket configurado.

    Args:
        path: Caminho dentro do bucket, ex: "visitas/uuid/relatorio.pdf"
        pdf_bytes: Conteúdo do PDF em bytes.

    Returns:
        URL pública do arquivo.
    """
    client = _client()
    bucket = settings.supabase_bucket

    # Remove arquivo anterior se existir (upsert)
    try:
        client.storage.from_(bucket).remove([path])
    except Exception:
        pass  # Ignora se não existia

    client.storage.from_(bucket).upload(
        path=path,
        file=pdf_bytes,
        file_options={"content-type": "application/pdf", "upsert": "true"},
    )

    url = client.storage.from_(bucket).get_public_url(path)
    logger.info("Upload concluído: %s", url)
    return url
