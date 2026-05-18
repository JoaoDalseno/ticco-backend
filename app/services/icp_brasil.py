"""
Mock do serviço ICP-Brasil para assinatura digital de documentos.

Em produção, este módulo integraria com um HSM ou API de certificado A1/A3.
Por ora retorna metadados simulados suficientes para o fluxo do receituário.
"""
import hashlib
import uuid
from datetime import datetime, timezone


class ICPBrasilService:
    """Gera metadados de assinatura digital simulados."""

    def gerar_numero_serie(self, visita_id: uuid.UUID) -> str:
        """Retorna número de série único para o receituário."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        sufixo = str(visita_id).replace("-", "")[:8].upper()
        return f"REC-{timestamp}-{sufixo}"

    def assinar(self, conteudo: bytes, crea: str) -> dict:
        """
        Simula assinatura digital do documento.

        Returns:
            dict com hash, timestamp e fingerprint do "certificado".
        """
        hash_doc = hashlib.sha256(conteudo).hexdigest()
        return {
            "algoritmo": "SHA256withRSA",
            "hash_documento": hash_doc,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "titular_crea": crea,
            "certificado_serie": f"MOCK-{hash_doc[:16].upper()}",
            "valido": True,
        }
