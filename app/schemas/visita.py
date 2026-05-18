import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.visita import StatusVisitaEnum


# ── Sub-schemas para dados_estruturados ──────────────────────────────────────

class PragaIdentificada(BaseModel):
    nome_popular: str
    nome_cientifico: Optional[str] = None
    severidade: str  # "leve", "media", "alta"
    area_afetada_ha: Optional[float] = None


class DoencaIdentificada(BaseModel):
    nome: str
    severidade: str  # "leve", "media", "alta"
    area_afetada_ha: Optional[float] = None


class Recomendacao(BaseModel):
    produto_sugerido: str
    ingrediente_ativo: Optional[str] = None
    dose: Optional[str] = None
    volume_calda: Optional[str] = None
    area_ha: Optional[float] = None
    prioridade: str  # "alta", "media", "baixa"
    justificativa: Optional[str] = None
    periodo_carencia_dias: Optional[int] = None
    epi: Optional[list[str]] = None


class VisitaDadosEstruturados(BaseModel):
    fazenda_identificada: Optional[str] = None
    talhao_identificado: Optional[str] = None
    estadio_fenologico: Optional[str] = None
    pragas_identificadas: list[PragaIdentificada] = []
    doencas_identificadas: list[DoencaIdentificada] = []
    recomendacoes: list[Recomendacao] = []
    observacoes_gerais: Optional[str] = None
    proxima_visita_sugerida: Optional[str] = None
    confianca_identificacao: str = "media"  # "alta", "media", "baixa"


# ── Schemas CRUD ─────────────────────────────────────────────────────────────

class VisitaCreate(BaseModel):
    agronomo_id: uuid.UUID
    fazenda_id: uuid.UUID
    talhao_id: uuid.UUID | None = None
    mensagem_id: uuid.UUID | None = None
    data_visita: date
    texto_bruto: str


class VisitaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    agronomo_id: uuid.UUID
    fazenda_id: uuid.UUID
    talhao_id: uuid.UUID | None
    mensagem_id: uuid.UUID | None
    data_visita: date
    texto_bruto: str
    dados_estruturados: dict
    pdf_relatorio_url: str | None
    pdf_receituario_url: str | None
    enviado_para_dono: bool
    status: StatusVisitaEnum
    erro_descricao: str | None
    created_at: datetime
    updated_at: datetime
