"""
Testes para geração de PDFs.

WeasyPrint requer bibliotecas nativas GTK/Pango que não estão disponíveis
no ambiente Windows de desenvolvimento. O módulo inteiro é substituído por
um stub no sys.modules antes de qualquer import do pdf_generator.
Em produção (Docker Linux) o WeasyPrint real é usado.
"""
import sys
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_PDF_MOCK = b"%PDF-1.4 fake pdf bytes for testing"

# weasyprint já foi substituído pelo stub no conftest.py —
# aqui apenas atualizamos o HTML stub para retornar _PDF_MOCK.
if "weasyprint" in sys.modules:
    class _FakeHTML:
        def __init__(self, string="", **kwargs):
            self._html = string

        def write_pdf(self):
            return _PDF_MOCK

    sys.modules["weasyprint"].HTML = _FakeHTML

from app.schemas.visita import (  # noqa: E402
    DoencaIdentificada,
    PragaIdentificada,
    Recomendacao,
    VisitaDadosEstruturados,
)
from app.services.icp_brasil import ICPBrasilService  # noqa: E402
from app.services.pdf_generator import gerar_receituario, gerar_relatorio  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def agronomo():
    return SimpleNamespace(
        nome="João Silva",
        crea="CREA-SP 12345/D",
        email="joao@ticco.com.br",
    )


@pytest.fixture
def fazenda():
    return SimpleNamespace(
        nome="Fazenda Bela Vista",
        dono_nome="Carlos Pereira",
        cidade="Pedregulho",
        estado="SP",
        area_total_ha=150.0,
    )


@pytest.fixture
def talhao():
    return SimpleNamespace(nome="Talhão 3", area_ha=40.0)


@pytest.fixture
def dados_completos():
    return VisitaDadosEstruturados(
        fazenda_identificada="Fazenda Bela Vista",
        talhao_identificado="Talhão 3",
        estadio_fenologico="granacao",
        pragas_identificadas=[
            PragaIdentificada(
                nome_popular="broca",
                nome_cientifico="Hypothenemus hampei",
                severidade="leve",
                area_afetada_ha=None,
            )
        ],
        doencas_identificadas=[
            DoencaIdentificada(
                nome="ferrugem",
                severidade="media",
                area_afetada_ha=15.0,
            )
        ],
        recomendacoes=[
            Recomendacao(
                produto_sugerido="Cuprozeb",
                ingrediente_ativo="cobre + mancozebe",
                dose="2 kg/ha",
                volume_calda="400 L/ha",
                area_ha=40.0,
                prioridade="alta",
                justificativa="Controle de ferrugem em estádio crítico",
                periodo_carencia_dias=7,
                epi=["luvas nitrílicas", "máscara PFF2", "avental impermeável"],
            )
        ],
        observacoes_gerais="Monitorar broca nas próximas semanas.",
        proxima_visita_sugerida="2026-05-25",
        confianca_identificacao="alta",
    )


@pytest.fixture
def dados_sem_recomendacoes():
    return VisitaDadosEstruturados(
        fazenda_identificada="Fazenda Bela Vista",
        pragas_identificadas=[
            PragaIdentificada(nome_popular="bicho-mineiro", severidade="leve")
        ],
        doencas_identificadas=[],
        recomendacoes=[],
        confianca_identificacao="media",
    )


# ── Helper: captura o HTML gerado antes do write_pdf ─────────────────────────

class CapturingHTML:
    _last_html: str = ""

    def __init__(self, string="", **kwargs):
        CapturingHTML._last_html = string

    def write_pdf(self):
        return _PDF_MOCK


# ── Testes do Relatório ───────────────────────────────────────────────────────

def test_gerar_relatorio_retorna_bytes(agronomo, fazenda, talhao, dados_completos):
    pdf = gerar_relatorio(agronomo, fazenda, talhao, dados_completos, date.today())
    assert pdf == _PDF_MOCK


def test_gerar_relatorio_html_contem_dados_fazenda(agronomo, fazenda, talhao, dados_completos):
    sys.modules["weasyprint"].HTML = CapturingHTML
    gerar_relatorio(agronomo, fazenda, talhao, dados_completos, date.today())
    html_str = CapturingHTML._last_html

    assert "Fazenda Bela Vista" in html_str
    assert "Carlos Pereira" in html_str
    assert "João Silva" in html_str
    assert "CREA-SP 12345/D" in html_str
    assert "ferrugem" in html_str
    assert "broca" in html_str
    assert "Cuprozeb" in html_str


def test_gerar_relatorio_sem_talhao(agronomo, fazenda, dados_completos):
    pdf = gerar_relatorio(agronomo, fazenda, None, dados_completos, date.today())
    assert pdf == _PDF_MOCK


def test_gerar_relatorio_sem_recomendacoes(agronomo, fazenda, talhao, dados_sem_recomendacoes):
    pdf = gerar_relatorio(agronomo, fazenda, talhao, dados_sem_recomendacoes, date.today())
    assert pdf == _PDF_MOCK


# ── Testes do Receituário ─────────────────────────────────────────────────────

def test_gerar_receituario_retorna_bytes(agronomo, fazenda, talhao, dados_completos):
    pdf = gerar_receituario(
        agronomo, fazenda, talhao, dados_completos, date.today(), "REC-20260518-ABCD1234"
    )
    assert pdf == _PDF_MOCK


def test_gerar_receituario_html_contem_dados(agronomo, fazenda, talhao, dados_completos):
    sys.modules["weasyprint"].HTML = CapturingHTML
    gerar_receituario(
        agronomo, fazenda, talhao, dados_completos, date.today(), "REC-20260518-ABCD1234"
    )
    html_str = CapturingHTML._last_html

    assert "REC-20260518-ABCD1234" in html_str
    assert "Cuprozeb" in html_str
    assert "cobre + mancozebe" in html_str
    assert "2 kg/ha" in html_str
    assert "luvas nitrílicas" in html_str
    assert "7 dias" in html_str


def test_gerar_receituario_sem_talhao_usa_area_fazenda(agronomo, fazenda, dados_completos):
    sys.modules["weasyprint"].HTML = CapturingHTML
    gerar_receituario(
        agronomo, fazenda, None, dados_completos, date.today(), "REC-TEST-00000000"
    )
    # Sem talhão, deve usar area_total_ha da fazenda (150.0)
    assert "150.0" in CapturingHTML._last_html


# ── Testes do ICPBrasilService ────────────────────────────────────────────────

def test_icp_gerar_numero_serie():
    icp = ICPBrasilService()
    visita_id = uuid.uuid4()
    numero = icp.gerar_numero_serie(visita_id)
    assert numero.startswith("REC-")
    assert len(numero) > 10


def test_icp_gerar_numero_serie_unico():
    icp = ICPBrasilService()
    ids = [uuid.uuid4() for _ in range(5)]
    numeros = [icp.gerar_numero_serie(i) for i in ids]
    sufixos = [n.split("-")[-1] for n in numeros]
    assert len(set(sufixos)) == 5


def test_icp_assinar_retorna_metadados():
    icp = ICPBrasilService()
    conteudo = b"conteudo do pdf de teste"
    resultado = icp.assinar(conteudo, "CREA-SP 12345/D")
    assert resultado["valido"] is True
    assert "hash_documento" in resultado
    assert len(resultado["hash_documento"]) == 64  # SHA-256 hex
    assert resultado["titular_crea"] == "CREA-SP 12345/D"
