import os
import json
import re
import asyncio
import aiohttp
import logging
from fpdf import FPDF
from datetime import datetime
from typing import List, Dict, Any
from pathlib import Path

from src.core.goals.protocol import (
    GoalBudget,
    GoalResult,
    GoalStatus,
    NotificationChannel,
)
from src.core.pipeline import SeekerPipeline
from src.providers.base import LLMRequest, invoke_with_fallback
from config.models import CognitiveRole

logger = logging.getLogger("seeker.event_radar")


class EventRadarGoal:
    """
    Radar de Eventos: Varredura metódica de cidades para mapeamento de calendários 2026.
    Resolvido arquiteturalmente via IBGE API (Zero Tokens) e JSON Lines (O(1) Memory).
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline
        self._status = GoalStatus.IDLE
        self._budget = GoalBudget(
            max_per_cycle_usd=0.05,
            max_daily_usd=0.50,
        )

        # Caminhos absolutos robustos (Prioriza Google Drive Desktop se ativo)
        self.project_root = Path(__file__).resolve().parent.parent.parent.parent

        gdrive_base = os.getenv("GDRIVE_PATH")
        if gdrive_base and os.path.exists(gdrive_base):
            self.data_dir = Path(gdrive_base) / "event_radar"
        else:
            self.data_dir = self.project_root / "data" / "event_radar"

        self.state_path = self.data_dir / "event_radar_state.json"
        self.results_path = self.data_dir / "event_radar_results.jsonl"

        self._ensure_directories()

    @property
    def name(self) -> str:
        return "event_radar"

    @property
    def interval_seconds(self) -> int:
        return 1800  # 30 minutos

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.TELEGRAM]

    def get_status(self) -> GoalStatus:
        return self._status

    def _ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _load_state_file(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            initial_state = {
                "estado_alvo": "Goiás",
                "uf": "GO",
                "cidade_atual": "Caldas Novas",
                "cidades_pendentes": [],
                "finalizado": False,
            }
            self._save_state_file(initial_state)
            return initial_state

        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Erro ao carregar estado do EventRadar: {e}")
            return {
                "estado_alvo": "Goiás",
                "uf": "GO",
                "cidade_atual": "Caldas Novas",
                "cidades_pendentes": [],
                "finalizado": False,
            }

    def _save_state_file(self, state: Dict[str, Any]):
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=4, ensure_ascii=False)

    def _save_results(self, new_events: List[Dict[str, Any]]):
        if not new_events:
            return
        with open(self.results_path, "a", encoding="utf-8") as f:
            for event in new_events:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    async def _fetch_cities_ibge(self, uf: str) -> List[str]:
        url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{uf}/municipios"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        return [city["nome"] for city in data]
                    return []
        except Exception as e:
            logger.error(f"Erro ao buscar cidades no IBGE: {e}")
            return []

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        state = self._load_state_file()

        if state.get("finalizado"):
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Varredura já concluída.")

        # Busca cidades se lista estiver vazia
        if not state.get("cidades_pendentes"):
            logger.info(f"Buscando cidades no IBGE para UF: {state.get('uf', 'GO')}")
            cities = await self._fetch_cities_ibge(state.get("uf", "GO"))
            if not cities:
                self._status = GoalStatus.ERROR
                return GoalResult(
                    success=False, summary="Falha ao obter cidades no IBGE."
                )

            # Remove a cidade inicial se ela estiver na lista (para evitar duplicação)
            if state["cidade_atual"] in cities:
                cities.remove(state["cidade_atual"])

            state["cidades_pendentes"] = cities
            self._save_state_file(state)

        # Seleciona próxima cidade
        if not state["cidades_pendentes"] and state.get("cidade_atual") is None:
            state["finalizado"] = True
            self._save_state_file(state)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True, summary=f"Varredura de {state['estado_alvo']} finalizada!"
            )

        cidade = state["cidade_atual"]
        estado_nome = state.get("estado_alvo", "Goiás")
        uf = state.get("uf", "GO")

        # Chama a função de mineração extraída
        events, cost_usd = await self.mine_city(cidade, estado_nome, uf)

        if events:
            self._save_results(events)

            # Gera Relatórios (PDF e CSV) para Sincronização Local
            try:
                await self._sync_reports(estado_nome)
            except Exception as e:
                logger.error(f"Erro ao gerar relatórios do radar: {e}")

        # Avança para a próxima cidade
        if state["cidades_pendentes"]:
            state["cidade_atual"] = state["cidades_pendentes"].pop(0)
        else:
            state["cidade_atual"] = None
            state["finalizado"] = True

        remaining = len(state["cidades_pendentes"])
        self._save_state_file(state)
        self._status = GoalStatus.IDLE

        if state["finalizado"]:
            msg_final = f"✅ Varredura de {estado_nome} finalizada! Próximo estado? (Edite data/event_radar_state.json)"
            return GoalResult(
                success=True,
                summary=msg_final,
                notification=msg_final,
                cost_usd=cost_usd,
            )

        progress_msg = (
            f"📍 <b>EventRadar:</b> {cidade} processada.\n"
            f"📅 Eventos extraídos: {len(events)}\n"
            f"🏙️ Restam em {estado_nome}: {remaining}"
        )

        return GoalResult(
            success=True,
            summary=f"{cidade} processada.",
            notification=progress_msg,
            cost_usd=cost_usd,
        )

    async def mine_city(self, cidade: str, estado_nome: str, uf: str) -> tuple[list[dict], float]:
        """
        Executa a varredura e extração de eventos para uma única cidade específica.
        Retorna a lista de eventos encontrados e o custo USD acumulado na operação.
        """
        # Estratégia multi-query: 5 buscas paralelas por cidade cobrindo fontes oficiais e populares
        queries = [
            f"calendario oficial de eventos 2026 prefeitura de {cidade} {estado_nome}",
            f"site:prefeitura.go.gov.br OR site:{cidade.replace(' ', '').lower()}.go.gov.br eventos festas 2026",
            f"festa religiosa padroeiro agropecuaria exposicao festival rodeio {cidade} GO 2026",
            f"aniversario da cidade de {cidade} {estado_nome} programacao 2026",
            f'"agenda cultural" OR "festivais" {cidade} {estado_nome} 2026',
        ]

        logger.info(f"Pesquisando {cidade} com {len(queries)} queries focadas")

        # Executa as 5 buscas em paralelo
        search_tasks = [
            self.pipeline.searcher.search(q, max_results=5) for q in queries
        ]
        search_results_list = await asyncio.gather(
            *search_tasks, return_exceptions=True
        )

        # Consolida os resultados
        all_snippets = []
        for r in search_results_list:
            if isinstance(r, Exception):
                continue
            try:
                ctx = (
                    r.to_context(max_results=5) if hasattr(r, "to_context") else str(r)
                )
                all_snippets.append(ctx)
            except Exception:
                all_snippets.append(str(r))

        contexto = (
            "\n---\n".join(all_snippets)
            if all_snippets
            else "(sem resultados de busca)"
        )

        prompt = (
            f"Você é o melhor extrator de inteligência de eventos do Brasil. Sua missão é investigar a cidade de {cidade} ({uf}).\n"
            f"Procure profundamente no contexto fornecido por:\n"
            f"- Eventos oficiais da prefeitura\n"
            f"- Festivais de música, gastronomia ou cultura\n"
            f"- Feiras agropecuárias, rodeios, exposições\n"
            f"- Festas religiosas (padroeiro(a), festas juninas)\n"
            f"- Aniversário da cidade\n\n"
            f"REGRA CRÍTICA: Toda cidade brasileira tem pelo menos:\n"
            f"- Aniversario da cidade (em algum mês do ano)\n"
            f"- Festas religiosas locais (padroeiro)\n"
            f"- Algum evento agropecuario ou cultural (carnaval, reveillon, etc)\n"
            f"Se o texto não mencionar explicitamente a data de 2026, INFIRA baseado na data tradicional e marque como aproximada.\n"
            f"Extraia o MÁXIMO de eventos possíveis.\n\n"
            f'Retorne APENAS um array JSON válido. Cada objeto: {{"nome", "data_estimada", "cidade"}}.\n'
            f'Exemplo: [{{"nome": "Aniversario de {cidade}", "data_estimada": "2026 (Mês a confirmar)", "cidade": "{cidade}"}}]\n\n'
            f"Resultados de pesquisa cruzada:\n{contexto[:5000]}"
        )

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Você extrai eventos de cidades brasileiras. Retorne APENAS JSON válido sem markdown.",
            temperature=0.2,
            max_tokens=4096,
        )

        events = []
        cost_usd = 0.0

        try:
            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                req,
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            cost_usd += getattr(resp, "cost_usd", 0.0)

            content = resp.text.strip()
            # Remove markdown code blocks se presentes
            content = re.sub(r"```(?:json)?", "", content).strip()
            match = re.search(r"\[.*\]", content, re.DOTALL)
            events = json.loads(match.group(0)) if match else []

            # Garante que todos os eventos têm o campo cidade
            for ev in events:
                if not ev.get("cidade"):
                    ev["cidade"] = cidade

        except Exception as e:
            logger.error(f"Erro de extração no EventRadar para {cidade}: {e}")
            events = []

        # ── KIMI DEEP RESEARCH FALLBACK ──
        # Se a busca padrão retornou 0 eventos e temos Kimi disponível,
        # ativa o "modo investigador" — o próprio LLM pesquisa na internet
        if not events and self.pipeline.api_keys.get("kimi"):
            logger.info(
                f"Ativando Kimi Deep Research para {cidade} (busca padrão retornou 0)"
            )
            try:
                kimi_prompt = (
                    f"Investigue profundamente a cidade de {cidade} ({uf}) e encontre TODOS os eventos, "
                    f"festas, feiras, rodeios, exposições agropecuárias, festas religiosas, aniversário da cidade, "
                    f"festivais e qualquer evento público programado para 2025 e 2026.\n\n"
                    f"Pesquise nos sites da prefeitura, portais de notícias locais e calendários culturais.\n"
                    f'Retorne APENAS um array JSON válido. Cada objeto: {{"nome", "data_estimada", "cidade"}}.'
                )
                kimi_req = LLMRequest(
                    messages=[{"role": "user", "content": kimi_prompt}],
                    system="Você é um investigador de eventos brasileiro. Pesquise na internet e retorne APENAS JSON.",
                    temperature=0.3,
                    max_tokens=4096,
                )
                kimi_resp = await invoke_with_fallback(
                    CognitiveRole.RESEARCH,
                    kimi_req,
                    self.pipeline.model_router,
                    self.pipeline.api_keys,
                )
                cost_usd += getattr(kimi_resp, "cost_usd", 0.0)
                kimi_content = re.sub(
                    r"```(?:json)?", "", kimi_resp.text.strip()
                ).strip()
                kimi_match = re.search(r"\[.*\]", kimi_content, re.DOTALL)
                if kimi_match:
                    events = json.loads(kimi_match.group(0))
                    for ev in events:
                        if not ev.get("cidade"):
                            ev["cidade"] = cidade
                    logger.info(f"Kimi encontrou {len(events)} eventos para {cidade}")
            except Exception as kimi_e:
                logger.warning(f"Kimi fallback falhou para {cidade}: {kimi_e}")

        return events, cost_usd

    async def _sync_reports(self, estado_nome: str):
        """Gera CSV e PDF atualizados para sincronização local."""
        if not self.results_path.exists():
            return

        # Lê todos os eventos do JSONL
        all_events = []
        with open(self.results_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_events.append(json.loads(line))

        if not all_events:
            return

        # 1. Gera CSV
        csv_name = f"Radar_Eventos_{estado_nome.replace(' ', '_')}.csv"
        csv_path = self.data_dir / csv_name
        import csv

        try:
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(
                    f,
                    fieldnames=["nome", "data_estimada", "cidade"],
                    extrasaction="ignore",
                )
                writer.writeheader()
                writer.writerows(all_events)
        except Exception as e:
            logger.error(f"Erro ao gerar CSV do radar: {e}")

        # 2. Gera PDF
        pdf_name = f"Relatorio_Radar_{estado_nome.replace(' ', '_')}.pdf"
        pdf_path = self.data_dir / pdf_name
        try:
            self._build_pdf_report(estado_nome, all_events, pdf_path)
        except Exception as e:
            logger.error(f"Erro ao gerar PDF do radar: {e}")

        # 3. Se o exportador de Drive estiver ativo (opcional, fallback)
        if self.pipeline.drive_exporter:
            try:
                # Tenta atualizar no Drive se possível, mas não trava se falhar por cota
                file_id = self.pipeline.drive_exporter.find_file_by_name(csv_name)
                if file_id:
                    self.pipeline.drive_exporter.update_file(
                        file_id, str(csv_path), "text/csv"
                    )
            except Exception as e:
                logger.debug(f"[event_radar] Drive sync failed (non-fatal): {e}")

    def _build_pdf_report(self, estado_nome: str, events: list, output_path: Path):
        """Gera um PDF formatado com os eventos encontrados."""
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        def clean(text):
            if not text:
                return ""
            return str(text).encode("latin-1", "replace").decode("latin-1")

        # Header
        pdf.set_font("Arial", "B", 16)
        pdf.cell(
            0, 10, clean(f"Radar de Eventos 2026 - {estado_nome}"), ln=True, align="C"
        )
        pdf.ln(5)

        pdf.set_font("Arial", "", 10)
        hoje = datetime.now().strftime("%d/%m/%Y %H:%M")
        pdf.cell(
            0,
            10,
            f"Gerado em: {hoje} | Total de Eventos Mapeados: {len(events)}",
            ln=True,
            align="R",
        )
        pdf.ln(5)

        # Tabela
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(200, 220, 255)
        pdf.cell(100, 10, "Evento", border=1, fill=True)
        pdf.cell(40, 10, "Data", border=1, fill=True)
        pdf.cell(50, 10, "Cidade", border=1, fill=True)
        pdf.ln()

        pdf.set_font("Arial", "", 10)
        for ev in events:
            pdf.cell(100, 8, clean(ev.get("nome", "N/A"))[:45], border=1)
            pdf.cell(40, 8, clean(ev.get("data_estimada", "N/A")), border=1)
            pdf.cell(50, 8, clean(ev.get("cidade", "N/A")), border=1)
            pdf.ln()

        pdf.output(str(output_path))
        logger.info(f"Relatório PDF do Radar salvo em: {output_path}")

    def serialize_state(self) -> dict:
        return {}  # Estado é persistido no arquivo externo

    def load_state(self, state: dict) -> None:
        pass


def create_goal(pipeline) -> EventRadarGoal:
    """Factory chamada pelo Goal Registry."""
    return EventRadarGoal(pipeline)
