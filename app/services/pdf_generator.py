"""
Geração de PDFs via WeasyPrint.

Gera dois documentos por visita:
  - Relatório de visita técnica
  - Receituário agronômico (quando há recomendações com produto fitossanitário)
"""
import html
import logging
from datetime import date

import weasyprint

from app.models.agronomo import Agronomo
from app.models.fazenda import Fazenda
from app.models.talhao import Talhao
from app.schemas.visita import VisitaDadosEstruturados

logger = logging.getLogger(__name__)

# Paleta Ticco
_CAFE = "#6B3410"
_VERDE = "#3D5A3D"
_CREME = "#F5EDE0"
_TERRA = "#3D2817"
_OURO = "#C9A961"

_CSS_BASE = f"""
@page {{ size: A4; margin: 2cm; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: Arial, sans-serif; font-size: 11pt; color: {_TERRA}; line-height: 1.6; background: #fff; }}
h1 {{ font-size: 18pt; color: {_CAFE}; margin-bottom: 4px; }}
h2 {{ font-size: 13pt; color: {_VERDE}; margin: 18px 0 6px; border-bottom: 2px solid {_OURO}; padding-bottom: 4px; }}
h3 {{ font-size: 11pt; margin: 10px 0 4px; }}
.header {{ display: flex; justify-content: space-between; align-items: flex-start;
           margin-bottom: 20px; padding-bottom: 14px; border-bottom: 3px solid {_CAFE}; }}
.header-logo {{ font-size: 26pt; font-weight: bold; color: {_CAFE}; letter-spacing: -1px; }}
.header-subtitle {{ font-size: 10pt; color: {_VERDE}; margin-top: 2px; }}
.header-info {{ text-align: right; font-size: 9pt; color: #555; }}
.info-box {{ background: {_CREME}; border-left: 4px solid {_OURO}; border-radius: 4px;
             padding: 10px 14px; margin: 10px 0; }}
.info-row {{ display: flex; gap: 8px; margin: 4px 0; }}
.info-label {{ font-weight: bold; min-width: 150px; color: {_CAFE}; }}
table {{ width: 100%; border-collapse: collapse; margin: 10px 0; font-size: 10pt; }}
th {{ background: {_VERDE}; color: #fff; padding: 7px 10px; text-align: left; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #e0d5cc; }}
tr:nth-child(even) td {{ background: #faf7f2; }}
.badge {{ display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 9pt; font-weight: bold; }}
.badge-alta {{ background: #fde8e8; color: #9b1c1c; }}
.badge-media {{ background: #fff3cd; color: #7d5a00; }}
.badge-leve {{ background: #d4edda; color: #155724; }}
.footer {{ margin-top: 30px; padding-top: 12px; border-top: 1px solid #ccc;
           font-size: 9pt; color: #888; text-align: center; }}
.assinatura {{ margin-top: 40px; text-align: center; }}
.assinatura-linha {{ border-top: 1px solid {_TERRA}; width: 300px; margin: 0 auto 4px;
                     padding-top: 6px; font-size: 10pt; }}
.num-serie {{ font-family: monospace; font-size: 9pt; color: #888; }}
"""


def _e(value: str | None) -> str:
    """HTML-escapa valores de usuário para evitar injeção de HTML nos PDFs."""
    return html.escape(str(value or ""), quote=True)


# Constantes usadas dentro de expressões f-string.
# Backslashes não são permitidos dentro de {} em Python < 3.12,
# por isso as aspas duplas ficam fora da f-string.
_SMALL_OPEN = '<br><small style="color:#666">'
_SMALL_CLOSE = "</small>"


def _badge(severidade: str) -> str:
    cls = _e(severidade.lower())
    return f'<span class="badge badge-{cls}">{_e(severidade.upper())}</span>'


def _data_fmt(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _html_to_pdf(html_str: str) -> bytes:
    return weasyprint.HTML(string=html_str).write_pdf()


# ── Relatório de Visita ───────────────────────────────────────────────────────

def _html_relatorio(
    agronomo: Agronomo,
    fazenda: Fazenda,
    talhao: Talhao | None,
    dados: VisitaDadosEstruturados,
    data_visita: date,
) -> str:
    pragas_html = ""
    if dados.pragas_identificadas:
        rows = "".join(
            f"<tr>"
            f"<td>{_e(p.nome_popular)}"
            f"{_SMALL_OPEN + _e(p.nome_cientifico) + _SMALL_CLOSE if p.nome_cientifico else ''}"
            f"</td>"
            f"<td>{_badge(p.severidade)}</td>"
            f"<td>{_e(str(p.area_afetada_ha)) + ' ha' if p.area_afetada_ha else '—'}</td>"
            f"</tr>"
            for p in dados.pragas_identificadas
        )
        pragas_html = f"""
        <h2>Pragas Detectadas</h2>
        <table>
          <tr><th>Praga</th><th>Severidade</th><th>Área Afetada</th></tr>
          {rows}
        </table>"""

    doencas_html = ""
    if dados.doencas_identificadas:
        rows = "".join(
            f"<tr>"
            f"<td>{_e(d.nome)}</td>"
            f"<td>{_badge(d.severidade)}</td>"
            f"<td>{_e(str(d.area_afetada_ha)) + ' ha' if d.area_afetada_ha else '—'}</td>"
            f"</tr>"
            for d in dados.doencas_identificadas
        )
        doencas_html = f"""
        <h2>Doenças Detectadas</h2>
        <table>
          <tr><th>Doença</th><th>Severidade</th><th>Área Afetada</th></tr>
          {rows}
        </table>"""

    recom_html = ""
    if dados.recomendacoes:
        rows = "".join(
            f"<tr>"
            f"<td>{_e(r.produto_sugerido)}"
            f"{_SMALL_OPEN + _e(r.ingrediente_ativo) + _SMALL_CLOSE if r.ingrediente_ativo else ''}"
            f"</td>"
            f"<td>{_e(r.dose) if r.dose else '—'}</td>"
            f"<td>{_e(str(r.area_ha)) + ' ha' if r.area_ha else '—'}</td>"
            f"<td>{_badge(r.prioridade)}</td>"
            f"<td>{_e(r.justificativa) if r.justificativa else '—'}</td>"
            f"</tr>"
            for r in dados.recomendacoes
        )
        recom_html = f"""
        <h2>Recomendações Técnicas</h2>
        <table>
          <tr><th>Produto / I.A.</th><th>Dose</th><th>Área</th><th>Prioridade</th><th>Justificativa</th></tr>
          {rows}
        </table>"""

    obs_html = (
        f"<h2>Observações Gerais</h2><p style='margin-top:6px'>{_e(dados.observacoes_gerais)}</p>"
        if dados.observacoes_gerais else ""
    )
    prox_html = (
        f'<div class="info-box" style="margin-top:14px">'
        f'<div class="info-row"><span class="info-label">Próxima visita sugerida:</span>'
        f"<span>{_e(dados.proxima_visita_sugerida)}</span></div></div>"
        if dados.proxima_visita_sugerida else ""
    )

    talhao_info = f" — {_e(talhao.nome)} ({talhao.area_ha} ha)" if talhao else ""
    estadio_html = (
        f"<div class='info-row'><span class='info-label'>Estádio fenológico:</span>"
        f"<span>{_e(dados.estadio_fenologico)}</span></div>"
        if dados.estadio_fenologico else ""
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Relatório de Visita Técnica</title>
<style>{_CSS_BASE}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-logo">ticco</div>
      <div class="header-subtitle">Relatório de Visita Técnica</div>
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
    <div class="info-row"><span class="info-label">Município/UF:</span><span>{_e(fazenda.cidade)}/{_e(fazenda.estado)}</span></div>
    <div class="info-row"><span class="info-label">Data da visita:</span><span>{_data_fmt(data_visita)}</span></div>
    {estadio_html}
  </div>

  {pragas_html}
  {doencas_html}
  {recom_html}
  {obs_html}
  {prox_html}

  <div class="assinatura">
    <div class="assinatura-linha">{_e(agronomo.nome)}<br>CREA: {_e(agronomo.crea)}</div>
    <p style="font-size:9pt;color:#777;margin-top:4px">Engenheiro Agrônomo Responsável</p>
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
          <td>{_e(r.produto_sugerido)}<br>
              <small style="color:#666">{_e(r.ingrediente_ativo) if r.ingrediente_ativo else '—'}</small></td>
          <td>{_e(r.dose) if r.dose else '—'}</td>
          <td>{_e(r.volume_calda) if r.volume_calda else '—'}</td>
          <td>{_e(str(r.area_ha)) + ' ha' if r.area_ha else '—'}</td>
          <td>{_e(str(r.periodo_carencia_dias)) + ' dias' if r.periodo_carencia_dias else '—'}</td>
          <td>{_badge(r.prioridade)}</td>
        </tr>"""
        for r in dados.recomendacoes
    )

    # Agrega todos os EPIs mencionados nas recomendações
    epis_todos: list[str] = []
    for r in dados.recomendacoes:
        if r.epi:
            epis_todos.extend(r.epi)
    epis_unicos = list(dict.fromkeys(epis_todos))
    epis_html = (
        "<ul style='margin-left:18px;margin-top:6px'>"
        + "".join(f"<li>{_e(e)}</li>" for e in epis_unicos)
        + "</ul>"
        if epis_unicos
        else "<p style='margin-top:6px'>Consulte a bula do produto.</p>"
    )

    return f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<title>Receituário Agronômico</title>
<style>{_CSS_BASE}</style></head>
<body>
  <div class="header">
    <div>
      <div class="header-logo">ticco</div>
      <div class="header-subtitle">Receituário Agronômico</div>
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
      <th>Dose</th>
      <th>Vol. Calda</th>
      <th>Área</th>
      <th>Carência</th>
      <th>Prioridade</th>
    </tr>
    {produtos_rows}
  </table>

  <h2>Equipamentos de Proteção Individual (EPIs)</h2>
  {epis_html}

  <div class="assinatura">
    <div class="assinatura-linha">{_e(agronomo.nome)}<br>CREA: {_e(agronomo.crea)}</div>
    <p style="font-size:9pt;color:#777;margin-top:4px">Engenheiro Agrônomo Responsável</p>
    <p class="num-serie" style="margin-top:8px">Receituário Nº {_e(numero_serie)}</p>
  </div>

  <div class="footer">
    Este receituário é válido para uma única aplicação na propriedade acima identificada.<br>
    Documento gerado pelo sistema Ticco — {_data_fmt(date.today())}
  </div>
</body></html>"""


# ── Funções públicas ──────────────────────────────────────────────────────────

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
