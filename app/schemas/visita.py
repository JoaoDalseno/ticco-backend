import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.visita import StatusVisitaEnum


# ── Sub-schemas para dados_estruturados ──────────────────────────────────────

class PragaDetectada(BaseModel):
    nome: str
    severidade: Literal["leve", "media", "alta"]
    area_afetada_pct: float | None = None
    observacao: str | None = None


class DoencaDetectada(BaseModel):
    nome: str
    severidade: Literal["leve", "media", "alta"]
    area_afetada_pct: float | None = None
    observacao: str | None = None


class ProdutoReceituario(BaseModel):
    nome_comercial: str
    ingrediente_ativo: str
    cultura: str = "Café"
    praga_alvo: str
    dose: str
    volume_calda: str | None = None
    epoca_aplicacao: str | None = None
    intervalo_seguranca_dias: int | None = None
    epis: list[str] = Field(default_factory=list)


class Recomendacao(BaseModel):
    tipo: str  # "aplicacao_quimica", "manejo_cultural", "monitoramento"
    descricao: str
    produto: str | None = None
    dose: str | None = None
    area_ha: float | None = None
    justificativa: str | None = None


class VisitaDadosEstruturados(BaseModel):
    """
    Schema retornado pelo Claude após processar o relato do agrônomo.
    Todos os campos são opcionais — Claude preenche o que conseguir identificar.
    """
    fazenda_identificada: str | None = None
    talhao_identificado: str | None = None
    confianca_identificacao: Literal["alta", "media", "baixa"] = "baixa"

    data_visita: str | None = None           # ISO date: "2026-05-14"
    estadio_fenologico: str | None = None    # ex: "granacao", "cereja"

    pragas: list[PragaDetectada] = Field(default_factory=list)
    doencas: list[DoencaDetectada] = Field(default_factory=list)
    recomendacoes: list[Recomendacao] = Field(default_factory=list)
    produtos_receituario: list[ProdutoReceituario] = Field(default_factory=list)

    observacoes_gerais: str | None = None
    proxima_visita: str | None = None        # ISO date


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
