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
from src.skills.event_radar.date_parser import enrich_event

logger = logging.getLogger("seeker.event_radar")


def report_state_names(data_dir: Path) -> list[str]:
    """Retorna os nomes dos estados que já produziram relatório (proxy de 'mapeado').

    Baseia-se na presença dos CSVs Radar_Eventos_{estado}.csv gerados por _sync_reports.
    """
    names = set()
    for p in data_dir.glob("Radar_Eventos_*.csv"):
        raw = p.stem[len("Radar_Eventos_"):]  # remove prefixo (.stem já tira .csv)
        names.add(raw.replace("_", " "))       # _sync_reports substitui espaço por _
    return sorted(names)


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
        state = self._load_state_file()
        if state.get("user_paused"):
            return GoalStatus.PAUSED
        return self._status

    def _ensure_directories(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def mapped_state_names(self) -> list[str]:
        """Estados que já geraram relatório CSV (foram varridos pelo radar)."""
        return report_state_names(self.data_dir)

    def _load_state_file(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            initial_state = {
                "estado_alvo": "Goiás",
                "uf": "GO",
                "cidade_atual": "Caldas Novas",
                "cidades_pendentes": [],
                "finalizado": False,
                "user_paused": False,
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
                "user_paused": False,
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
        state = self._load_state_file()

        if state.get("user_paused"):
            self._status = GoalStatus.PAUSED
            return GoalResult(success=True, summary="Varredura pausada pelo usuário.")

        self._status = GoalStatus.RUNNING

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
            if state.get("cidade_atual") in cities:
                cities.remove(state["cidade_atual"])

            state["cidades_pendentes"] = cities

            # Se a cidade atual for None, define a primeira da lista como atual (evita NoneType crash)
            if state.get("cidade_atual") is None and cities:
                state["cidade_atual"] = state["cidades_pendentes"].pop(0)

            self._save_state_file(state)

        # Monta a lista de cidades a processar neste lote (máximo 5)
        batch_cities = []
        if state.get("cidade_atual"):
            batch_cities.append(state["cidade_atual"])
            state["cidade_atual"] = None

        limit = 5
        while len(batch_cities) < limit and state.get("cidades_pendentes"):
            next_city = state["cidades_pendentes"].pop(0)
            batch_cities.append(next_city)

        if not batch_cities:
            state["finalizado"] = True
            self._save_state_file(state)
            self._status = GoalStatus.IDLE
            return GoalResult(
                success=True, summary=f"Varredura de {state.get('estado_alvo', 'Goiás')} finalizada!"
            )

        estado_nome = state.get("estado_alvo", "Goiás")
        uf = state.get("uf", "GO")

        all_new_events = []
        total_cost = 0.0
        results_summary = []

        # Processamento das cidades do lote
        for idx, cidade in enumerate(batch_cities):
            if idx > 0:
                # Pequeno delay entre chamadas de cidades para respeitar RPM do Gemini Free Tier (15 RPM)
                await asyncio.sleep(2.0)
            
            logger.info(f"[event_radar] Processando cidade {idx+1}/{len(batch_cities)}: {cidade}")
            events, cost_usd = await self.mine_city(cidade, estado_nome, uf)
            total_cost += cost_usd
            
            if events:
                all_new_events.extend(events)
            
            results_summary.append(f"• <b>{cidade}</b>: {len(events)} evento(s) extraído(s)")

        if all_new_events:
            self._save_results(all_new_events)
            # Gera Relatórios (PDF e CSV) para Sincronização Local
            try:
                await self._sync_reports(estado_nome)
            except Exception as e:
                logger.error(f"Erro ao gerar relatórios do radar: {e}")

        # Define qual será a cidade atual para o próximo ciclo
        if state["cidades_pendentes"]:
            state["cidade_atual"] = state["cidades_pendentes"].pop(0)
            state["finalizado"] = False
        else:
            state["cidade_atual"] = None
            state["finalizado"] = True

        remaining = len(state["cidades_pendentes"])
        self._save_state_file(state)
        self._status = GoalStatus.IDLE

        # Mensagem formatada
        results_str = "\n".join(results_summary)
        
        if state["finalizado"]:
            msg_final = (
                f"✅ <b>Varredura de {estado_nome} finalizada!</b>\n\n"
                f"Lote final processado:\n{results_str}\n\n"
                f"Próximo estado? (Edite data/event_radar_state.json)"
            )
            return GoalResult(
                success=True,
                summary=f"Varredura de {estado_nome} finalizada.",
                notification=msg_final,
                cost_usd=total_cost,
            )

        progress_msg = (
            f"📍 <b>EventRadar — Lote Processado:</b>\n"
            f"{results_str}\n\n"
            f"🏙️ Restam em {estado_nome}: {remaining} cidade(s) pendente(s)."
        )

        return GoalResult(
            success=True,
            summary=f"Lote de {len(batch_cities)} cidades processadas.",
            notification=progress_msg,
            cost_usd=total_cost,
        )

    async def mine_city(
        self,
        cidade: str,
        estado_nome: str = "Goiás",
        uf: str = "GO",
        save_to_jsonl: bool = False,
    ) -> tuple[list[dict], float]:
        """
        Executa a varredura e extração de eventos para uma única cidade específica.
        Cada evento retornado já passa por enrich_event (mes/mes_fim/precisao).
        Se save_to_jsonl=True, persiste os eventos no JSONL global (idempotência
        de duplicatas é responsabilidade do consumidor, igual ao run_cycle).
        Retorna a lista de eventos encontrados e o custo USD acumulado na operação.
        """
        queries = [
            f"calendario oficial de eventos 2026 prefeitura de {cidade} {estado_nome}",
            f"site:prefeitura.{uf.lower()}.gov.br OR site:{cidade.replace(' ', '').lower()}.{uf.lower()}.gov.br eventos festas 2026",
            f"festa religiosa padroeiro agropecuaria exposicao festival rodeio {cidade} {uf} 2026",
            f"aniversario da cidade de {cidade} {estado_nome} programacao 2026",
            f'"agenda cultural" OR "festivais" {cidade} {estado_nome} 2026',
        ]

        logger.info(f"Pesquisando {cidade} com {len(queries)} queries focadas")

        # Executa as 5 buscas em paralelo
        search_tasks = [
            self.pipeline.searcher.search(q, max_results=5, bypass_limit=True) for q in queries
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

        cost_usd = 0.0
        aniversario_evento = None
        
        # ── BUSCA DE ANIVERSÁRIO GARANTIDO DA CIDADE VIA GEMINI SEARCH GROUNDING ──
        if self.pipeline.api_keys.get("gemini"):
            try:
                grounding_prompt = f"Qual a data de comemoração de aniversário (dia e mês) do município de {cidade} em {estado_nome} ({uf})? Responda de forma curta em uma única linha no formato: 'Dia e Mês de Aniversário' (ex: 14 de Novembro)."
                grounding_req = LLMRequest(
                    messages=[{"role": "user", "content": grounding_prompt}],
                    system="Você é um assistente de inteligência de dados geográficos. Responda de forma extremamente curta.",
                    temperature=0.0,
                    max_tokens=100,
                    tools=[{"googleSearch": {}}]
                )
                
                from config.models import ModelConfig
                gemini_config = ModelConfig(
                    provider="gemini",
                    model_id="gemini-2.5-flash",
                    display_name="Gemini 2.5 Flash",
                    cost_per_1m_input=0.075,
                    cost_per_1m_output=0.30,
                    rpm_limit=15
                )
                from src.providers.base import create_provider
                gemini_prov = create_provider(gemini_config, self.pipeline.api_keys)
                
                logger.info(f"Buscando aniversário de {cidade} via Gemini Search Grounding...")
                g_resp = await gemini_prov.complete(grounding_req)
                cost_usd += getattr(g_resp, "cost_usd", 0.0)
                
                resposta_aniversario = g_resp.text.strip()
                logger.info(f"Gemini Grounding respondeu aniversário de {cidade}: {resposta_aniversario}")
                
                if len(resposta_aniversario) > 5 and len(resposta_aniversario) < 100:
                    aniversario_evento = {
                        "nome": f"Aniversário de {cidade}",
                        "data_estimada": f"{resposta_aniversario} (Garantido)",
                        "cidade": cidade
                    }
            except Exception as e:
                logger.warning(f"Falha ao obter aniversário de {cidade} via Gemini Grounding: {e}")

        req = LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            system="Você extrai eventos de cidades brasileiras. Retorne APENAS JSON válido sem markdown.",
            temperature=0.2,
            max_tokens=4096,
            tools=[{"googleSearch": {}}] if self.pipeline.api_keys.get("gemini") else None
        )

        events = []

        try:
            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                req,
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            cost_usd += getattr(resp, "cost_usd", 0.0)

            content = resp.text.strip()
            content = re.sub(r"```(?:json)?", "", content).strip()
            match = re.search(r"\[.*\]", content, re.DOTALL)
            events = json.loads(match.group(0)) if match else []

            # Garante que todos os eventos têm os campos cidade e uf
            for ev in events:
                if not ev.get("cidade"):
                    ev["cidade"] = cidade
                # Injeta UF do radar (necessário para resolver estado nos leads)
                if not ev.get("uf"):
                    ev["uf"] = uf

            # Injeta ou atualiza o aniversário de forma garantida
            if aniversario_evento:
                ja_tem = any("aniversario" in str(ev.get("nome", "")).lower() for ev in events)
                if not ja_tem:
                    events.append(aniversario_evento)
                else:
                    for ev in events:
                        if "aniversario" in str(ev.get("nome", "")).lower():
                            ev["data_estimada"] = aniversario_evento["data_estimada"]

        except Exception as e:
            logger.error(f"Erro de extração no EventRadar para {cidade}: {e}")
            if aniversario_evento:
                events = [aniversario_evento]
            else:
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
                        if not ev.get("uf"):
                            ev["uf"] = uf
                    logger.info(f"Kimi encontrou {len(events)} eventos para {cidade}")
            except Exception as kimi_e:
                logger.warning(f"Kimi fallback falhou para {cidade}: {kimi_e}")

        # Enriquece todos os eventos com mes/mes_fim/precisao (date_parser)
        events = [enrich_event(ev) for ev in events]

        if save_to_jsonl and events:
            self._save_results(events)

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
