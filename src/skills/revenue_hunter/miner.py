import asyncio
import logging
import random
import json
import time
import os

from src.core.pipeline import SeekerPipeline
from src.core.utils import parse_llm_json
from src.providers.base import LLMRequest, invoke_with_fallback
from src.core.goals.protocol import (
    AutonomousGoal, GoalBudget, GoalResult, GoalStatus, NotificationChannel,
)
from src.skills.revenue_hunter.prompts import (
    TARGET_REGIONS,
    TARGET_EVENTS,
    TRIGGER_KEYWORDS,
    BANT_SCORE_PROMPT,
    ENRICH_PROMPT,
    DOSSIER_PROMPT,
)
from config.models import CognitiveRole
from src.skills.revenue_hunter.crm_store import CRMStore

log = logging.getLogger("seeker.hunter")


class RevenueMiner:
    """
    Goal Autônomo de Mineração de Oportunidades (Trigger Events).

    v3 — Pipeline de 3 fases:
      1. Discovery: busca web + BANT scoring (schema rico)
      2. Enrich: busca específica por lead quente (contatos reais)
      3. Dossier: dossiê completo com pitch pronto + PDF

    Melhorias:
    - Schema BANT com sub-scores (B/A/N/T 0-25 cada)
    - Enriquecimento por lead: 2ª busca específica extrai contatos reais
    - Campos novos: orcamento_estimado, artistas_anteriores, edicoes_anteriores,
      whatsapp, website, facebook, decisor_nome, decisor_cargo
    - Dossiê com pitch pronto + estratégia de abordagem + próximos passos
    - PDF com fpdf2 (unicode correto, sem hack latin-1)
    """

    def __init__(self, pipeline: SeekerPipeline):
        self.pipeline = pipeline

        self._budget = GoalBudget(
            max_per_cycle_usd=0.10,   # +0.05 pelo enriquecimento
            max_daily_usd=0.60,
        )

        # Dedup: {target_normalizado: timestamp}
        self.LEAD_COOLDOWN_SECONDS = 7 * 86400
        self._notified_leads: dict[str, float] = {}

        # Cooldown de combos (evitar repetir a mesma pesquisa)
        self.COMBO_COOLDOWN_SECONDS = 48 * 3600
        self._last_combos: dict[str, float] = {}

        # Performance tracking
        self._combo_stats: dict[str, dict] = {}
        self._status = GoalStatus.IDLE
        self.crm_store = CRMStore(self.pipeline.memory._db)
        
        # Async initialization will be handled in step() if needed, but safe to just run a task
        asyncio.create_task(self.crm_store.init_tables())

    @property
    def name(self) -> str:
        return "revenue_hunter"

    @property
    def interval_seconds(self) -> int:
        return 3600  # 1x/hora

    @property
    def budget(self) -> GoalBudget:
        return self._budget

    @property
    def channels(self) -> list[NotificationChannel]:
        return [NotificationChannel.BOTH]

    def get_status(self) -> GoalStatus:
        return self._status

    # ── Ciclo principal ───────────────────────────────────

    async def run_cycle(self) -> GoalResult:
        self._status = GoalStatus.RUNNING
        cycle_cost = 0.0
        cycle_data: dict = {}

        regiao, evento, trigger = self._pick_combo()
        combo_key = f"{regiao}|{evento}|{trigger}"

        from datetime import date
        current_year = date.today().year

        query = f'{evento} {regiao} {trigger} {current_year}'
        log.info(f"[hunter] Minerando: {query}")

        # ── FASE 1: Discovery ──────────────────────────────
        search_res = await self.pipeline.searcher.search(query, max_results=10)
        if not search_res.results:
            log.info("[hunter] Nenhum resultado hoje.")
            self._track_combo(combo_key, hot=False)
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhum resultado de busca", cost_usd=0.0)

        contexto_busca = search_res.to_context(max_results=8)

        resp_bant = await invoke_with_fallback(
            CognitiveRole.FAST,
            LLMRequest(
                messages=[{"role": "user", "content": BANT_SCORE_PROMPT.format(
                    query=query,
                    search_context=contexto_busca,
                    current_year=current_year,
                )}],
                system="Você é uma IA de dados B2B. Responda APENAS com JSON válido.",
                temperature=0.1,
            ),
            self.pipeline.model_router,
            self.pipeline.api_keys,
        )
        cycle_cost += resp_bant.cost_usd

        try:
            dados_score = parse_llm_json(resp_bant.text)
            leads = dados_score.get("leads", [])
        except Exception as e:
            log.warning(f"[hunter] JSON inválido no BANT: {e}")
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="JSON inválido no scoring", cost_usd=cycle_cost)

        if not leads:
            log.info("[hunter] Nenhum lead extraído.")
            self._track_combo(combo_key, hot=False)
            self._status = GoalStatus.IDLE
            return GoalResult(success=True, summary="Nenhum lead no ciclo", cost_usd=cycle_cost)

        log.info(f"[hunter] {len(leads)} leads extraídos. Filtrando quentes (score >= 60)...")

        # ── FASE 2: Enriquecimento por lead quente ─────────
        hot_leads = []
        for lead in leads:
            score = lead.get("score", 0)
            nome = lead.get("nome_evento", "Evento Desconhecido")
            cidade = lead.get("cidade", "GO")

            if score < 60:
                log.info(f"[hunter] Lead frio ({score}): {nome}")
                self._track_combo(combo_key, hot=False)
                continue

            target_key = _normalize_target(nome)
            if self._is_recently_notified(target_key):
                log.info(f"[hunter] {nome} — já notificado recentemente, skip.")
                continue

            if self._budget.exhausted:
                log.warning(f"[hunter] Budget esgotado antes de enriquecer {nome}.")
                break

            log.info(f"[hunter] 🎯 HOT ({score}): {nome} — iniciando enriquecimento...")

            lead = await self._enrich_lead(lead, nome, cidade)
            cycle_cost += lead.pop("_enrich_cost", 0.0)
            hot_leads.append((target_key, lead))

        # ── FASE 3: Dossiê + PDF ───────────────────────────
        notificacoes = []
        for target_key, lead in hot_leads:
            if self._budget.exhausted:
                break

            nome = lead.get("nome_evento", target_key)
            score = lead.get("score", 0)

            try:
                # --- Lógica LUMEN (Design) ---
                score_val = lead.get("score", 0)
                filled = int(score_val / 10)
                score_bar = "█" * filled + "░" * (10 - filled)
                
                score_label = "FRIO"
                if score_val >= 90: score_label = "🔥 ALTO IMPACTO"
                elif score_val >= 80: score_label = "🟢 QUENTE"
                elif score_val >= 70: score_label = "🟡 INTERESSANTE"
                else: score_label = "⚪ AVALIAR"

                links = []
                wa = lead.get("whatsapp")
                if wa and wa != "N/A":
                    clean_wa = "".join(filter(str.isdigit, str(wa)))
                    links.append(f'<a href="https://wa.me/{clean_wa}">WA</a>')
                
                ig = lead.get("instagram")
                if ig and ig != "N/A":
                    clean_ig = str(ig).replace("@", "").strip()
                    links.append(f'<a href="https://instagram.com/{clean_ig}">IG</a>')
                
                web = lead.get("website")
                if web and web != "N/A":
                    links.append(f'<a href="{web}">WEB</a>')
                
                link_card = " | ".join(links) if links else "N/A"

                resp_dossier = await invoke_with_fallback(
                    CognitiveRole.SYNTHESIS,
                    LLMRequest(
                        messages=[{"role": "user", "content": DOSSIER_PROMPT.format(
                            lead_json_string=json.dumps(lead, indent=2, ensure_ascii=False),
                            nome_evento=nome,
                            cidade=lead.get("cidade", "GO"),
                            score=score,
                            score_bar=score_bar,
                            score_label=score_label,
                            tipo_contratante=lead.get("tipo_contratante", "N/A"),
                            periodo=lead.get("periodo", "N/A"),
                            porte_estimado=lead.get("porte_estimado", "N/A"),
                            edicoes_anteriores=lead.get("edicoes_anteriores", "N/A"),
                            artistas_anteriores=lead.get("artistas_anteriores") or "Não identificados",
                            orcamento_estimado=lead.get("orcamento_estimado") or "A qualificar",
                            decisor_nome=lead.get("decisor_nome") or lead.get("decisor_provavel", "N/A"),
                            decisor_cargo=lead.get("decisor_cargo", "N/A"),
                            link_card=link_card,
                            sinais_contratacao=lead.get("sinais_contratacao", "N/A"),
                        )}],
                        system="Você é o Seeker SDR. Formate o dossiê em HTML para Telegram.",
                        temperature=0.3,
                        max_tokens=2500,
                    ),
                    self.pipeline.model_router,
                    self.pipeline.api_keys,
                )
                cycle_cost += resp_dossier.cost_usd
                dossier_text = resp_dossier.text.strip()

                # --- RETHINK (Gatekeeper Autoavaliação) ---
                rethink_prompt = (
                    "Você é o módulo RETHINK. Avalie o dossiê abaixo e pratique o 'Raciocínio Aberto'.\n"
                    "Regra: O dossiê deve parecer um texto humano estruturado com tópicos, emojis e quebras de linha claras.\n"
                    "Se o texto parecer truncado, for um bloco gigante de texto, apresentar formato JSON puro "
                    "ou parecer incompleto, você DEVE rejeitá-lo.\n\n"
                    "Responda ESTRITAMENTE em formato JSON:\n"
                    "{\n"
                    '  "decision": "OK" ou "REJEITAR",\n'
                    '  "reason": "Sua explicação técnica para o usuário sobre o porquê desta decisão."\n'
                    "}\n\n"
                    f"DOSSIÊ:\n{dossier_text[:1000]}"
                )
                resp_rethink = await invoke_with_fallback(
                    CognitiveRole.FAST,
                    LLMRequest(
                        messages=[{"role": "user", "content": rethink_prompt}],
                        system="Você é o Gatekeeper de qualidade visual. Retorne apenas JSON válido sem marcações markdown extra.",
                        temperature=0.0,
                        max_tokens=150,
                    ),
                    self.pipeline.model_router,
                    self.pipeline.api_keys,
                )
                cycle_cost += resp_rethink.cost_usd

                try:
                    rethink_data = parse_llm_json(resp_rethink.text)
                    decision = str(rethink_data.get("decision", "REJEITAR")).upper()
                    reason = rethink_data.get("reason", "Motivo não informado.")
                    
                    if decision == "REJEITAR":
                        log.warning(f"[hunter/rethink] 🛑 Dossiê interceptado para {nome}.\nMotivo Oculto: {reason}\nFricção atuou para poupar o usuário.")
                        cycle_data["rethink_blocks"] = cycle_data.get("rethink_blocks", 0) + 1
                        continue
                except Exception as eval_e:
                    log.warning(f"[hunter/rethink] Falha ao parear avaliação do gatekeeper: {eval_e}. Rejeitando por segurança.")
                    cycle_data["rethink_blocks"] = cycle_data.get("rethink_blocks", 0) + 1
                    continue
                # ----------------------------------------

                notificacoes.append(dossier_text)
                self._notified_leads[target_key] = time.time()
                self._track_combo(combo_key, hot=True)

                # Gera PDF
                pdf_path = _build_pdf(lead, dossier_text, target_key)
                if pdf_path:
                    cycle_data.setdefault("pdfs", []).append(pdf_path)
                    cycle_data["pdf_path"] = pdf_path
                    
                # Save to CRM Database
                await self.crm_store.save_lead(
                    lead=lead,
                    target_key=target_key,
                    pdf_path=pdf_path or "",
                    dossier_html=dossier_text,
                    discovered_at=time.time()
                )

            except Exception as e:
                log.error(f"[hunter] Erro gerando dossiê de {nome}: {e}", exc_info=True)

        self._status = GoalStatus.IDLE

        if notificacoes:
            count = len(notificacoes)
            header = f"🚨 <b>REVENUE HUNTER — {count} ALVO(S) EM GOIÁS</b> 🚨\n\n"
            final = header + "\n\n➖➖➖➖➖➖\n\n".join(notificacoes)
            cycle_data["leads_count"] = count
            return GoalResult(
                success=True,
                summary=f"{count} HOT LEADS com dossiê gerado",
                notification=final,
                cost_usd=cycle_cost,
                data=cycle_data,
            )

        return GoalResult(
            success=True,
            summary=f"Ciclo concluído — {len(leads)} leads avaliados, nenhum quente",
            cost_usd=cycle_cost,
        )

    # ── Fase 2: Enriquecimento ────────────────────────────

    async def _enrich_lead(self, lead: dict, nome: str, cidade: str) -> dict:
        """2ª busca específica por evento → extrai contatos reais."""
        tipo_contratante = str(lead.get("tipo_contratante", "")).lower()
        
        # Estratégia Agressiva: se for evento público, pesquisa contato direto do órgão gestor
        if "prefeitur" in tipo_contratante or "gostosa" in tipo_contratante or "prefeitur" in nome.lower() or "secretar" in tipo_contratante:
            enrich_query = f'("{nome}" OR "prefeitura municipal de {cidade}") contato telefone secretario cultura whatsapp -jusbrasil'
        else:
            enrich_query = f'"{nome}" "{cidade}" contato telefone instagram whatsapp 2025 2026'

        enrich_cost = 0.0

        try:
            enrich_res = await self.pipeline.searcher.search(enrich_query, max_results=5)
            if not enrich_res.results:
                lead["_enrich_cost"] = 0.0
                return lead

            enrich_context = enrich_res.to_context(max_results=5)
            lead_atual = json.dumps(lead, indent=2, ensure_ascii=False)

            resp = await invoke_with_fallback(
                CognitiveRole.FAST,
                LLMRequest(
                    messages=[{"role": "user", "content": ENRICH_PROMPT.format(
                        nome_evento=nome,
                        cidade=cidade,
                        lead_atual=lead_atual,
                        enrich_context=enrich_context,
                    )}],
                    system="Você é uma IA de inteligência comercial. Responda APENAS com JSON válido.",
                    temperature=0.0,
                    max_tokens=400,
                ),
                self.pipeline.model_router,
                self.pipeline.api_keys,
            )
            if not resp or not resp.text.strip():
                log.warning(f"[hunter] Provedor {resp.provider if resp else 'N/A'} retornou vazio para {nome}. Pulando enriquecimento.")
                lead["_enrich_cost"] = resp.cost_usd if resp else 0.0
                return lead

            enriched = parse_llm_json(resp.text)
            # Merge: atualiza apenas campos não-nulos do enriquecimento
            for key, val in enriched.items():
                if val and str(val).lower() != "null" and val != "N/A":
                    lead[key] = val

            log.info(
                f"[hunter] Enriquecido: {nome} | "
                f"tel={lead.get('telefone')} | ig={lead.get('instagram')} | "
                f"wa={lead.get('whatsapp')} | decisor={lead.get('decisor_nome')}"
            )

        except Exception as e:
            log.warning(f"[hunter] Enriquecimento falhou para {nome}: {e}")

        lead["_enrich_cost"] = enrich_cost
        return lead

    # ── Seleção inteligente de combos ─────────────────────

    def _pick_combo(self) -> tuple[str, str, str]:
        """70% exploitation + 30% exploration. Cooldown de 48h."""
        now = time.time()

        def is_available(k: str) -> bool:
            return (now - self._last_combos.get(k, 0)) >= self.COMBO_COOLDOWN_SECONDS

        def commit(r, e, t):
            self._last_combos[f"{r}|{e}|{t}"] = now
            return r, e, t

        # Exploitation
        if self._combo_stats and random.random() > 0.3:
            scored = [
                (k, s["hot_leads"] / max(s["attempts"], 1))
                for k, s in self._combo_stats.items()
                if is_available(k)
            ]
            scored.sort(key=lambda x: x[1], reverse=True)
            top = scored[:5]
            if top and top[0][1] > 0:
                chosen = random.choice([k for k, _ in top])
                parts = chosen.split("|")
                if len(parts) == 3:
                    return commit(parts[0], parts[1], parts[2])

        # Exploration
        for _ in range(50):
            r, e, t = (
                random.choice(TARGET_REGIONS),
                random.choice(TARGET_EVENTS),
                random.choice(TRIGGER_KEYWORDS),
            )
            if is_available(f"{r}|{e}|{t}"):
                return commit(r, e, t)

        # Fallback
        r, e, t = (
            random.choice(TARGET_REGIONS),
            random.choice(TARGET_EVENTS),
            random.choice(TRIGGER_KEYWORDS),
        )
        return commit(r, e, t)

    def _track_combo(self, combo_key: str, hot: bool):
        if combo_key not in self._combo_stats:
            self._combo_stats[combo_key] = {"attempts": 0, "hot_leads": 0}
        self._combo_stats[combo_key]["attempts"] += 1
        if hot:
            self._combo_stats[combo_key]["hot_leads"] += 1

    def _is_recently_notified(self, target_key: str) -> bool:
        last = self._notified_leads.get(target_key)
        return last is not None and (time.time() - last) < self.LEAD_COOLDOWN_SECONDS

    def _cleanup_expired(self):
        now = time.time()
        self._notified_leads = {
            k: ts for k, ts in self._notified_leads.items()
            if (now - ts) < self.LEAD_COOLDOWN_SECONDS
        }
        self._last_combos = {
            k: ts for k, ts in self._last_combos.items()
            if (now - ts) < self.COMBO_COOLDOWN_SECONDS
        }

    # ── Persistência ──────────────────────────────────────

    def serialize_state(self) -> dict:
        self._cleanup_expired()
        return {
            "notified_leads": self._notified_leads,
            "combo_stats": self._combo_stats,
            "last_combos": self._last_combos,
        }

    def load_state(self, state: dict) -> None:
        self._notified_leads = state.get("notified_leads", {})
        self._combo_stats = state.get("combo_stats", {})
        self._last_combos = state.get("last_combos", {})
        log.info(
            f"[hunter] Estado carregado: {len(self._notified_leads)} leads, "
            f"{len(self._combo_stats)} combos, {len(self._last_combos)} em cooldown."
        )

    def get_crm_leads(self, limit: int = 10) -> list[dict]:
        """
        Retorna os últimos leads qualificados lendo os PDFs gerados em data/leads/.
        Não depende de nenhum DB — usa o filesystem como fonte de verdade.
        """
        leads_dir = os.path.join(os.getcwd(), "data", "leads")
        if not os.path.isdir(leads_dir):
            return []

        entries = []
        for fname in os.listdir(leads_dir):
            if not fname.endswith(".pdf"):
                continue
            fpath = os.path.join(leads_dir, fname)
            try:
                mtime = os.path.getmtime(fpath)
                fsize = os.path.getsize(fpath)
                # Nome do arquivo: Dossier_<slug>_<timestamp>.pdf
                slug = fname.replace("Dossier_", "").rsplit("_", 1)[0]
                name = slug.replace("_", " ").title()
                entries.append({
                    "name": name,
                    "pdf_path": fpath,
                    "timestamp": mtime,
                    "size_bytes": fsize,
                    "filename": fname,
                })
            except Exception:
                continue

        # Ordena pelos mais recentes
        entries.sort(key=lambda x: x["timestamp"], reverse=True)
        return entries[:limit]


# ── Helpers ───────────────────────────────────────────────

def _normalize_target(target: str) -> str:
    return target.strip().lower()


def _build_pdf(lead: dict, dossier_text: str, target_key: str) -> str | None:
    """Gera PDF estruturado do lead após qualificação."""
    try:
        from fpdf import FPDF
        
        def clean(text: str) -> str:
            if not text: return ""
            # Strip emojis e caracteres não ANSI que quebram a Helvetica
            t = str(text).replace('—', '-').replace('–', '-').replace('“', '"').replace('”', '"')
            return t.encode('latin-1', 'ignore').decode('latin-1')
            
        leads_dir = os.path.join(os.getcwd(), "data", "leads")
        os.makedirs(leads_dir, exist_ok=True)
        
        safe_name = target_key.replace(" ", "_")[:40]
        file_name = f"Dossier_{safe_name}_{int(time.time())}.pdf"
        file_path = os.path.join(leads_dir, file_name)

        pdf = FPDF()
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Cabeçalho
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, clean("Revenue Hunter - Dossie de Lead"), align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "I", 10)
        from datetime import datetime
        pdf.cell(0, 6, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} pelo Seeker.Bot",
                 align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        nome = clean(lead.get('nome_evento', 'Desconhecido'))
        cidade = clean(lead.get('cidade', 'Sem Local'))
        score = lead.get('score', 0)

        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 8, f"{nome} - {cidade}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, f"Score BANT: {score}/100", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        # Campos estruturados
        fields = [
            ("Contratante", lead.get("tipo_contratante", "N/A")),
            ("Período", lead.get("periodo", "N/A")),
            ("Porte", lead.get("porte_estimado", "N/A")),
            ("Edições anteriores", lead.get("edicoes_anteriores", "N/A")),
            ("Artistas anteriores", lead.get("artistas_anteriores") or "Não identificados"),
            ("Orçamento estimado", lead.get("orcamento_estimado") or "A qualificar"),
        ]
        contact_fields = [
            ("Decisor", f"{lead.get('decisor_nome') or lead.get('decisor_provavel', 'N/A')} "
                        f"({lead.get('decisor_cargo', '')})"),
            ("WhatsApp", lead.get("whatsapp") or "N/A"),
            ("Telefone", lead.get("telefone") or "N/A"),
            ("Instagram", lead.get("instagram") or "N/A"),
            ("Website", lead.get("website") or "N/A"),
            ("Facebook", lead.get("facebook") or "N/A"),
        ]

        def section(title: str):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_fill_color(240, 240, 240)
            pdf.cell(0, 7, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

        def field_row(label: str, value: str):
            try:
                pdf.set_font("Helvetica", "B", 10)
                start_y = pdf.get_y()
                pdf.set_xy(pdf.l_margin, start_y)
                pdf.cell(45, 6, clean(f"{label}:"))
                pdf.set_font("Helvetica", "", 10)
                pdf.set_xy(pdf.l_margin + 45, start_y)
                pdf.multi_cell(0, 6, clean(value or "N/A"))
                pdf.set_xy(pdf.l_margin, pdf.get_y())
            except Exception as e:
                log.warning(f"[hunter] PDF skip row {label}: {e}")

        section("Perfil do Evento")
        for label, val in fields:
            field_row(label, str(val))
        pdf.ln(3)

        section("Contatos Levantados")
        for label, val in contact_fields:
            field_row(label, str(val))
        pdf.ln(3)

        section("Sinais de Contratação")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, clean(lead.get("sinais_contratacao", "N/A")))
        pdf.ln(3)

        section("Justificativa Estratégica")
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, clean(lead.get("justificativa", "N/A")))
        pdf.ln(3)

        # Dossiê completo (sem tags HTML)
        import re
        clean_dossier = re.sub(r"<[^>]+>", "", dossier_text)
        section("Dossiê Completo (Texto do Seeker)")
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, clean(clean_dossier))

        pdf.output(file_path)
        log.info(f"[hunter] PDF salvo: {file_path}")
        return file_path

    except Exception as e:
        log.warning(f"[hunter] Falha ao gerar PDF: {e}")
        return None
