"""
Geração de PDFs via WeasyPrint.

Gera dois documentos por visita:
  - Relatório de visita técnica
  - Receituário agronômico (quando há produtos fitossanitários)
"""
import html
import io
import logging
from datetime import date

from xhtml2pdf import pisa

from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.talhao import Talhao
from app.schemas.visita import VisitaDadosEstruturados

logger = logging.getLogger(__name__)

_CSS_BASE = """
@page { size: A4; margin: 2cm; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, sans-serif; font-size: 11pt; color: #222; line-height: 1.5; }
h1 { font-size: 16pt; color: #2d5a1b; margin-bottom: 4px; }
h2 { font-size: 13pt; color: #2d5a1b; margin: 16px 0 6px; border-bottom: 1px solid #ccc; padding-bottom: 3px; }
h3 { font-size: 11pt; margin: 10px 0 4px; }
.header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 2px solid #2d5a1b; }
.header-logo { font-size: 22pt; font-weight: bold; color: #2d5a1b; letter-spacing: -1px; }
.header-info { text-align: right; font-size: 9pt; color: #555; }
.info-box { background: #f5f5f0; border: 1px solid #ddd; border-radius: 4px; padding: 10px 14px; margin: 10px 0; }
.info-row { display: flex; gap: 8px; margin: 3px 0; }
.info-label { font-weight: bold; min-width: 140px; color: #444; }
table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 10pt; }
th { background: #2d5a1b; color: white; padding: 6px 8px; text-align: left; }
td { padding: 5px 8px; border-bottom: 1px solid #eee; }
tr:nth-child(even) td { background: #f9f9f9; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 9pt; font-weight: bold; }
.badge-alta { background: #fde8e8; color: #c00; }
.badge-media { background: #fff3cd; color: #856404; }
.badge-leve { background: #d4edda; color: #155724; }
.footer { margin-top: 30px; padding-top: 12px; border-top: 1px solid #ccc; font-size: 9pt; color: #777; text-align: center; }
.assinatura { margin-top: 40px; text-align: center; }
.assinatura-linha { border-top: 1px solid #222; width: 280px; margin: 0 auto 4px; padding-top: 4px; }
.num-serie { font-family: monospace; font-size: 9pt; color: #888; }
"""


def _e(value: str | None) -> str:
    """HTML-escapa strings de usuário para prevenir injeção de HTML nos PDFs."""
    return html.escape(str(value or ""), quote=True)


def _badge(severidade: str) -> str:
    return f'<span class="badge badge-{_e(severidade)}">{_e(severidade.upper())}</span>'


def _data_fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


# ── Relatório de Visita ───────────────────────────────────────────────────────

def _html_relatorio(
    agronomo: Agronomo,
    fazenda: Fazenda,
    talhao: Talhao | None,
    dados: VisitaDadosEstruturados,
    data_visita: date,
) -> str:
    pragas_html = ""
    if dados.pragas:
        rows = "".join(
            f"<tr><td>{_e(p.nome)}</td><td>{_badge(p.severidade)}</td>"
            f"<td>{_e(str(p.area_afetada_pct)) if p.area_afetada_pct else '—'}%</td><td>{_e(p.observacao) if p.observacao else '—'}</td></tr>"
            for p in dados.pragas
        )
        pragas_html = f"""
        <h2>Pragas Detectadas</h2>
        <table>
          <tr><th>Praga</th><th>Severidade</th><th>Área</th><th>Observação</th></tr>
          {rows}
        </table>"""

    doencas_html = ""
    if dados.doencas:
        rows = "".join(
            f"<tr><td>{_e(d.nome)}</td><td>{_badge(d.severidade)}</td>"
            f"<td>{_e(str(d.area_afetada_pct)) if d.area_afetada_pct else '—'}%</td><td>{_e(d.observacao) if d.observacao else '—'}</td></tr>"
            for d in dados.doencas
        )
        doencas_html = f"""
        <h2>Doenças Detectadas</h2>
        <table>
          <tr><th>Doença</th><th>Severidade</th><th>Área</th><th>Observação</th></tr>
          {rows}
        </table>"""

    recom_html = ""
    if dados.recomendacoes:
        items = "".join(
            f"<tr><td>{_e(r.tipo.replace('_', ' ').title())}</td><td>{_e(r.descricao)}</td>"
            f"<td>{_e(r.produto) if r.produto else '—'}</td><td>{_e(r.dose) if r.dose else '—'}</td>"
            f"<td>{_e(str(r.area_ha)) if r.area_ha else '—'} ha</td></tr>"
            for r in dados.recomendacoes
        )
        recom_html = f"""
        <h2>Recomendações Técnicas</h2>
        <table>
          <tr><th>Tipo</th><th>Descrição</th><th>Produto</th><th>Dose</th><th>Área</th></tr>
          {items}
        </table>"""

    obs = f"<h2>Observações Gerais</h2><p>{_e(dados.observacoes_gerais)}</p>" if dados.observacoes_gerais else ""
    prox = (
        f'<div class="info-box"><div class="info-row"><span class="info-label">Próxima visita:</span>'
        f"<span>{_e(dados.proxima_visita)}</span></div></div>"
        if dados.proxima_visita else ""
    )

    talhao_info = f" — {_e(talhao.nome)} ({talhao.area_ha} ha)" if talhao else ""
    estadio = f"<div class='info-row'><span class='info-label'>Estádio fenológico:</span><span>{_e(dados.estadio_fenologico)}</span></div>" if dados.estadio_fenologico else ""

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Relatório de Visita Técnica</title>
<style>{_CSS_BASE}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-logo">ticco</div>
      <div style="font-size:10pt;color:#555">Relatório de Visita Técnica</div>
    </div>
    <div class="header-info">
      Emitido em {_data_fmt(date.today())}<br>
      {_e(agronomo.nome)}<br>CREA: {_e(agronomo.crea)}
    </div>
  </div>

  <h2>Identificação</h2>
  <div class="info-box">
    <div class="info-row"><span class="info-label">Fazenda:</span><span>{_e(fazenda.nome)}{talhao_info}</span></div>
    <div class="info-row"><span class="info-label">Proprietário:</span><span>{_e(fazenda.dono_nome)}</span></div>
    <div class="info-row"><span class="info-label">Município:</span><span>{_e(fazenda.cidade)}/{_e(fazenda.estado)}</span></div>
    <div class="info-row"><span class="info-label">Data da visita:</span><span>{_data_fmt(data_visita)}</span></div>
    {estadio}
  </div>

  {pragas_html}
  {doencas_html}
  {recom_html}
  {obs}
  {prox}

  <div class="assinatura">
    <div class="assinatura-linha">{_e(agronomo.nome)}<br>CREA: {_e(agronomo.crea)}</div>
    <p style="font-size:9pt;color:#777">Responsável Técnico</p>
  </div>

  <div class="footer">
    Documento gerado pelo sistema Ticco — {_data_fmt(date.today())}
  </div>
</body></html>"""


# ── Receituário Agronômico ────────────────────────────────────────────────────

def _html_receituario(
    agronomo: Agronomo,
    fazenda: Fazenda,
    talhao: Talhao | None,
    dados: VisitaDadosEstruturados,
    data_visita: date,
    numero_serie: str,
) -> str:
    area_ha = talhao.area_ha if talhao else fazenda.area_total_ha
    talhao_nome = talhao.nome if talhao else "—"

    produtos_rows = "".join(
        f"""<tr>
          <td>{_e(p.nome_comercial)}<br><small style="color:#555">{_e(p.ingrediente_ativo)}</small></td>
          <td>{_e(p.cultura)}</td>
          <td>{_e(p.praga_alvo)}</td>
          <td>{_e(p.dose)}</td>
          <td>{_e(p.volume_calda) if p.volume_calda else '—'}</td>
          <td>{p.intervalo_seguranca_dias or '—'} dias</td>
        </tr>"""
        for p in dados.produtos_receituario
    )

    epis_todos: list[str] = []
    for p in dados.produtos_receituario:
        epis_todos.extend(p.epis)
    epis_unicos = list(dict.fromkeys(epis_todos))
    epis_html = (
        "<ul>" + "".join(f"<li>{_e(e)}</li>" for e in epis_unicos) + "</ul>"
        if epis_unicos else "<p>Consulte a bula do produto.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Receituário Agronômico</title>
<style>{_CSS_BASE}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-logo">ticco</div>
      <div style="font-size:10pt;color:#555">Receituário Agronômico</div>
    </div>
    <div class="header-info">
      <span class="num-serie">Nº {_e(numero_serie)}</span><br>
      Emitido em {_data_fmt(date.today())}
    </div>
  </div>

  <h2>Responsável Técnico</h2>
  <div class="info-box">
    <div class="info-row"><span class="info-label">Nome:</span><span>{_e(agronomo.nome)}</span></div>
    <div class="info-row"><span class="info-label">CREA:</span><span>{_e(agronomo.crea)}</span></div>
    <div class="info-row"><span class="info-label">E-mail:</span><span>{_e(agronomo.email) if agronomo.email else '—'}</span></div>
  </div>

  <h2>Propriedade / Produtor</h2>
  <div class="info-box">
    <div class="info-row"><span class="info-label">Produtor:</span><span>{_e(fazenda.dono_nome)}</span></div>
    <div class="info-row"><span class="info-label">Propriedade:</span><span>{_e(fazenda.nome)}</span></div>
    <div class="info-row"><span class="info-label">Talhão:</span><span>{_e(talhao_nome)}</span></div>
    <div class="info-row"><span class="info-label">Município/UF:</span><span>{_e(fazenda.cidade)}/{_e(fazenda.estado)}</span></div>
    <div class="info-row"><span class="info-label">Área tratada:</span><span>{area_ha} ha</span></div>
    <div class="info-row"><span class="info-label">Data da visita:</span><span>{_data_fmt(data_visita)}</span></div>
  </div>

  <h2>Produtos Recomendados</h2>
  <table>
    <tr>
      <th>Produto / Ingrediente Ativo</th>
      <th>Cultura</th>
      <th>Alvo</th>
      <th>Dose</th>
      <th>Vol. Calda</th>
      <th>Carência</th>
    </tr>
    {produtos_rows}
  </table>

  <h2>Equipamentos de Proteção Individual (EPIs)</h2>
  {epis_html}

  <div class="assinatura">
    <div class="assinatura-linha">{_e(agronomo.nome)}<br>CREA: {_e(agronomo.crea)}</div>
    <p style="font-size:9pt;color:#777">Engenheiro Agrônomo Responsável</p>
    <p class="num-serie" style="margin-top:8px">Receituário Nº {_e(numero_serie)}</p>
  </div>

  <div class="footer">
    Este receituário é válido para uma única aplicação na propriedade acima identificada.<br>
    Documento gerado pelo sistema Ticco — {_data_fmt(date.today())}
  </div>
</body></html>"""


# ── Funções públicas ──────────────────────────────────────────────────────────

def _html_to_pdf(html: str) -> bytes:
    buf = io.BytesIO()
    result = pisa.pisaDocument(io.StringIO(html), buf)
    if result.err:
        raise RuntimeError(f"Erro ao gerar PDF: {result.err}")
    return buf.getvalue()


def gerar_relatorio(
    agronomo: Agronomo,
    fazenda: Fazenda,
    talhao: Talhao | None,
    dados: VisitaDadosEstruturados,
    data_visita: date,
) -> bytes:
    """Gera o PDF do relatório de visita e retorna os bytes."""
    return _html_to_pdf(_html_relatorio(agronomo, fazenda, talhao, dados, data_visita))


def gerar_receituario(
    agronomo: Agronomo,
    fazenda: Fazenda,
    talhao: Talhao | None,
    dados: VisitaDadosEstruturados,
    data_visita: date,
    numero_serie: str,
) -> bytes:
    """Gera o PDF do receituário agronômico e retorna os bytes."""
    return _html_to_pdf(_html_receituario(agronomo, fazenda, talhao, dados, data_visita, numero_serie))
