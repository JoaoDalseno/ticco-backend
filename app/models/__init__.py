# Importa todos os models para o Alembic detectar via Base.metadata
from app.models.base import Base, TimestampMixin
from app.models.agronomo import Agronomo, PlanoEnum, StatusPagamentoEnum
from app.models.fazenda import Fazenda
from app.models.talhao import Talhao
from app.models.mensagem import Mensagem, DirecaoEnum, TipoEnum
from app.models.visita import Visita, StatusVisitaEnum
from app.models.receituario import Receituario, StatusReceituarioEnum

__all__ = [
    "Base",
    "TimestampMixin",
    "Agronomo",
    "PlanoEnum",
    "StatusPagamentoEnum",
    "Fazenda",
    "Talhao",
    "Mensagem",
    "DirecaoEnum",
    "TipoEnum",
    "Visita",
    "StatusVisitaEnum",
    "Receituario",
    "StatusReceituarioEnum",
]
