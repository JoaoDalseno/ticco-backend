"""
Pipeline de IA — Claude claude-sonnet-4-5 estrutura o relato de visita técnica.
"""
import json

import anthropic

from app.core.ontologia.loader import OntologiaLoader
from app.core.prompts.visita_extractor import RETRY_PROMPT, SYSTEM_PROMPT, USER_PROMPT
from app.schemas.visita import VisitaDadosEstruturados
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


class AIProcessor:

    def __init__(self):
        self.client = anthropic.AsyncAnthropic()
        self.ontologia = OntologiaLoader.load()

    async def extract_visita_data(
        self,
        texto_bruto: str,
        fazendas_contexto: list[dict],
    ) -> VisitaDadosEstruturados:
        """
        Extrai dados estruturados de um relato de visita.
        Faz até 2 tentativas em caso de JSON inválido.
        """
        schema_str = json.dumps(
            VisitaDadosEstruturados.model_json_schema(),
            ensure_ascii=False,
            indent=2,
        )
        system = SYSTEM_PROMPT.format(
            ontologia=json.dumps(self.ontologia, ensure_ascii=False, indent=2),
            fazendas_contexto=json.dumps(fazendas_contexto, ensure_ascii=False, indent=2),
            schema=schema_str,
        )

        messages = [
            {"role": "user", "content": USER_PROMPT.format(texto_bruto=texto_bruto)}
        ]

        for tentativa in range(2):
            response = await self.client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=2000,
                system=system,
                messages=messages,
            )
            raw = response.content[0].text.strip()

            try:
                data = json.loads(raw)
                result = VisitaDadosEstruturados(**data)
                logger.info(
                    f"Visita estruturada — fazenda: {result.fazenda_identificada} "
                    f"— confiança: {result.confianca_identificacao}"
                )
                return result
            except Exception as e:
                logger.warning(f"Tentativa {tentativa + 1} falhou: {e}")
                if tentativa == 0:
                    messages.append({"role": "assistant", "content": raw})
                    messages.append({"role": "user", "content": RETRY_PROMPT.format(erro=str(e))})
                else:
                    raise ValueError(f"AI retornou JSON inválido após 2 tentativas: {e}")

    async def gerar_resumo_whatsapp(
        self,
        dados: VisitaDadosEstruturados,
        nome_agronomo: str,
    ) -> str:
        """Gera texto formatado pro WhatsApp com o resumo da visita."""
        n_pragas = len(dados.pragas_identificadas)
        n_doencas = len(dados.doencas_identificadas)
        n_recs = len(dados.recomendacoes)

        pragas_txt = ""
        if dados.pragas_identificadas:
            itens = [
                f"  • {p.nome_popular} — {p.severidade}"
                for p in dados.pragas_identificadas
            ]
            pragas_txt = "\n".join(itens)

        doencas_txt = ""
        if dados.doencas_identificadas:
            itens = [
                f"  • {d.nome} — {d.severidade}"
                for d in dados.doencas_identificadas
            ]
            doencas_txt = "\n".join(itens)

        recs_txt = ""
        if dados.recomendacoes:
            itens = [
                f"  {i+1}. {r.produto_sugerido}"
                f"{f' — {r.dose}' if r.dose else ''}"
                f" ({r.prioridade})"
                for i, r in enumerate(dados.recomendacoes)
            ]
            recs_txt = "\n".join(itens)

        msg = "*Visita registrada* 📋\n\n"
        msg += f"*Fazenda:* {dados.fazenda_identificada or 'Não identificada'}\n"

        if dados.talhao_identificado:
            msg += f"*Talhão:* {dados.talhao_identificado}\n"

        if dados.estadio_fenologico:
            msg += f"*Estádio:* {dados.estadio_fenologico}\n"

        if n_pragas > 0:
            msg += f"\n*Pragas ({n_pragas}):*\n{pragas_txt}\n"

        if n_doencas > 0:
            msg += f"\n*Doenças ({n_doencas}):*\n{doencas_txt}\n"

        if n_recs > 0:
            msg += f"\n*Recomendações ({n_recs}):*\n{recs_txt}\n"

        if dados.proxima_visita_sugerida:
            msg += f"\n*Próxima visita:* {dados.proxima_visita_sugerida}\n"

        msg += "\n_Relatório e receituário sendo gerados... 👇_"

        return msg
