import logging
from aiogram import Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
import html
import asyncio
import re
from config.models import CognitiveRole
from src.core.pipeline import SeekerPipeline
from src.providers.base import _rate_limiters
import os
import signal
from src.channels.telegram.formatter import split_message
from src.skills.tech_scout.goal import CATEGORY_NAMES

log = logging.getLogger("seeker.telegram.system")


def setup_system_handlers(dp: Dispatcher, pipeline: SeekerPipeline):
    @dp.message(F.text == "/status")
    async def cmd_status(message: Message):
        router = pipeline.model_router
        lines = ["<b>Seeker.Bot — Status</b>\n"]
        for role in CognitiveRole:
            try:
                model = router.get(role)
                lines.append(f"<b>{role.value}</b>: {model.display_name}")
            except ValueError:
                lines.append(f"<b>{role.value}</b>: ⚠️ não configurado")
        lines.append("\n<b>Providers na arbitragem:</b>")
        for m in router.get_all_for_arbitrage():
            lines.append(f"  → {m.display_name} ({m.provider})")
        try:
            stats = await pipeline.memory.get_episode_stats()
            facts = await pipeline.memory.get_facts(limit=999)
            lines.append("\n<b>Memória:</b>")
            lines.append(f"  {stats['total_episodes']} episódios | {len(facts)} fatos")
            lines.append(f"  Custo acumulado: ${stats['total_cost_usd']:.4f}")
            if stats["avg_latency_ms"]:
                lines.append(f"  Latência média: {stats['avg_latency_ms']}ms")
            # Métricas de uso de memória semântica
            mem_stats = pipeline.get_memory_stats()
            if mem_stats["responses"] > 0:
                lines.append(
                    f"  Uso de fatos: {mem_stats['with_facts']}/{mem_stats['responses']} "
                    f"respostas ({mem_stats['usage_rate_pct']}%) · "
                    f"média {mem_stats['avg_facts_per_response']} fatos/resp"
                )
            # Session info
            active = pipeline.session.active_sessions
            if active:
                lines.append(f"  Sessões ativas: {len(active)}")

            # Goal Engine status
            scheduler = dp.get("scheduler")
            if scheduler:
                lines.append(f"\n{scheduler.get_status_report()}")

            # OODA Loop statistics (FASE 4)
            ooda_loop = dp.get("ooda_loop")
            if ooda_loop:
                ooda_stats = ooda_loop.get_stats()
                if ooda_stats["total_iterations"] > 0:
                    lines.append("\n<b>🔄 OODA Loop:</b>")
                    lines.append(f"  {ooda_stats['total_iterations']} iterações")
                    lines.append(
                        f"  Success rate: {ooda_stats['success_rate']:.0%} "
                        f"| Bloqueadas: {ooda_stats['blocked_count']}"
                    )
                    lines.append(
                        f"  Latência média: {ooda_stats['avg_latency_ms']:.0f}ms"
                    )

        except Exception:
            lines.append("\n<b>Memória:</b> inicializando...")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/saude")
    async def cmd_saude(message: Message):
        try:
            scheduler = dp.get("scheduler")
            if not scheduler:
                await message.answer(
                    "❌ Goal scheduler não inicializado.", parse_mode=ParseMode.HTML
                )
                return

            dashboard = scheduler.get_health_dashboard()
            lines = ["<b>📊 Health Dashboard dos Goals</b>\n"]

            # Global summary
            lines.append("<b>🌍 Global:</b>")
            lines.append(
                f"  Total: {dashboard['summary']['total_goals']} goals | "
                f"Taxa média: {dashboard['summary']['avg_success_rate']:.1f}% | "
                f"Custo: ${dashboard['summary']['total_cost_today']:.4f}"
            )

            # Budget
            spent = dashboard["global_budget"]["spent"]
            limit = dashboard["global_budget"]["limit"]
            pct = spent / limit * 100 if limit > 0 else 0
            emoji = "🔴" if pct > 80 else ("🟡" if pct > 50 else "🟢")
            lines.append(
                f"\n<b>💰 Budget Global:</b> {emoji} ${spent:.4f}/${limit} ({pct:.0f}%)"
            )

            # Per-goal metrics
            lines.append("\n<b>📈 Goals Detalhados:</b>")
            for goal_name, metrics in sorted(dashboard["goals"].items()):
                m = metrics["metrics"]
                status_emoji = {
                    "RUNNING": "🟢",
                    "IDLE": "⏸",
                    "PAUSED": "🟡",
                    "ERROR": "🔴",
                }.get(metrics["status"], "⚪")

                # Trend sparkline
                trend_emoji = m.get("trend", "➡️")

                # Success rate with recent comparison
                recent = m.get("recent_5_success_rate", 0)
                rate = m["success_rate"]
                rate_str = f"{rate:.0f}% ({recent:.0f}% recent)"

                lines.append(
                    f"  {status_emoji} <b>{goal_name}</b> {trend_emoji}\n"
                    f"    ✅ Taxa: {rate_str} | "
                    f"⏱️ Latência: {m['avg_latency']:.2f}s | "
                    f"💵 Total: ${m['total_cost']:.4f}\n"
                    f"    📊 Ciclos: {m['total_cycles']} | "
                    f"🔴 Falhas: {m['consecutive_failures']}"
                )

                # Budget per-goal
                budget = metrics["budget"]
                budget_pct = (
                    budget["spent_today"] / budget["limit"] * 100
                    if budget["limit"] > 0
                    else 0
                )
                budget_emoji = (
                    "🔴" if budget_pct > 80 else ("🟡" if budget_pct > 50 else "🟢")
                )
                lines.append(
                    f"    {budget_emoji} Budget: ${budget['spent_today']:.4f}/${budget['limit']} ({budget_pct:.0f}%)"
                )

            # Friction metrics
            friction = dashboard["friction_metrics"]
            if sum(friction.values()) > 0:
                lines.append("\n<b>🛡️ Fricção Controlada:</b>")
                if friction["rethinks_blocked"] > 0:
                    lines.append(f"  🛑 Rethinks: {friction['rethinks_blocked']}")
                if friction["sara_edits"] > 0:
                    lines.append(f"  🛠️ SARA Edits: {friction['sara_edits']}")
                if friction["rate_limits"] > 0:
                    lines.append(f"  🚷 Rate Limits: {friction['rate_limits']}")

            # Last update timestamp
            import datetime

            ts = datetime.datetime.fromtimestamp(dashboard["timestamp"])
            lines.append(f"\n<i>Atualizado em: {ts.strftime('%H:%M:%S')}</i>")

            msg = "\n".join(lines)

            # Split if too long
            for part in split_message(msg):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[saude] Goal scheduler not properly initialized: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Goal scheduler não está disponível", parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[saude] Invalid health dashboard data: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao processar dados de saúde", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[saude] Unexpected error in health dashboard: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard de saúde",
                parse_mode=ParseMode.HTML,
            )

    @dp.message(F.text == "/audit_sara")
    async def cmd_audit_sara(message: Message):
        """Dashboard de Integridade Operacional (Hallucinations + SARA + Budget)"""
        try:
            report = pipeline.get_integrity_report()
            await message.answer(report, parse_mode=ParseMode.HTML)
        except Exception as e:
            log.error(f"[audit_sara] Erro ao gerar relatório: {e}", exc_info=True)
            await message.answer("❌ Erro ao gerar relatório de integridade.")

    @dp.message(F.text == "/perf")
    async def cmd_perf(message: Message):
        """Dashboard de performance do sistema"""
        try:
            report = pipeline.format_perf_report()
            await message.answer(report, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[perf] Performance reporter not available: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de performance não está disponível",
                parse_mode=ParseMode.HTML,
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[perf] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao gerar relatório de performance", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[perf] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao gerar relatório", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/perf_detailed")
    async def cmd_perf_detailed(message: Message):
        """Métricas detalhadas de performance por fase + Sprint 11 Optimizations"""
        try:
            # Relatório Sprint 11 (Cascade + Cache + Batch)
            sprint11_report = pipeline.get_sprint11_report()

            # Dashboard geral
            dashboard = pipeline.get_performance_dashboard()
            goals = dashboard["goals"]

            lines = [sprint11_report]

            if goals:
                # Formata por goal
                lines.append("<b>📊 GOALS PERFORMANCE</b>\n")
                for goal_id, metrics in list(goals.items())[:5]:  # Top 5 goals
                    lines.append(
                        f"<b>{goal_id}</b>\n"
                        f"  Cycles: {metrics['cycles']} | Success: {metrics['success_rate']}\n"
                        f"  Cost: {metrics['total_cost']} | Avg Latency: {metrics['avg_latency_ms']}ms\n"
                    )

            detailed = "".join(lines)

            # Dividir em chunks se muito grande
            for part in split_message(detailed):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[perf_detailed] Performance dashboard not available: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Dashboard de performance não está disponível",
                parse_mode=ParseMode.HTML,
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[perf_detailed] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao processar métricas de performance",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[perf_detailed] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao carregar métricas detalhadas",
                parse_mode=ParseMode.HTML,
            )

    @dp.message(F.text == "/cascade_status")
    async def cmd_cascade_status(message: Message):
        """Status detalhado da API Cascade — 6 tiers com health checks"""
        try:
            # Health status de cada tier
            health = pipeline.cascade_adapter.get_health_status()
            cost_analysis = pipeline.cascade_adapter.get_cost_analysis()

            # Formatar status dos tiers
            lines = ["<b>🔀 API CASCADE STATUS (6 Tiers)</b>\n"]
            lines.append(f"<b>Timestamp:</b> {health['timestamp'][:19]}\n")
            lines.append(f"<b>Overall Health:</b> {health['overall_health']}\n\n")

            lines.append("<b>📊 TIER BREAKDOWN:</b>\n")
            for tier_name, tier_status in health["tiers"].items():
                health_emoji = "✅" if tier_status["is_healthy"] else "⚠️"
                lines.append(
                    f"{health_emoji} <b>{tier_name.upper()}</b>\n"
                    f"  Success Rate: {tier_status['success_rate']}\n"
                    f"  Avg Latency: {tier_status['avg_latency_ms']}ms\n"
                    f"  Cost/Call: {tier_status['avg_cost_usd']}\n"
                    f"  Fallbacks: {tier_status['fallback_count']}\n"
                )
                if tier_status["last_error"]:
                    lines.append(f"  Last Error: {tier_status['last_error'][:50]}...\n")

            lines.append("\n<b>💰 COST ANALYSIS:</b>\n")
            lines.append(f"Total Calls: {cost_analysis['total_calls']}\n")
            lines.append(f"Total Cost: ${cost_analysis['total_cost_usd']}\n")
            lines.append(f"Avg Cost/Call: ${cost_analysis['average_cost_per_call']}\n")
            lines.append(
                f"Savings vs NIM: {cost_analysis['estimated_savings_vs_nim']}\n"
            )

            # Error breakdown
            if cost_analysis.get("error_breakdown"):
                lines.append("\n<b>🔴 ERROR BREAKDOWN:</b>\n")
                for tier_name, errors in cost_analysis["error_breakdown"].items():
                    if errors:
                        lines.append(f"<b>{tier_name}:</b> {errors}\n")

            status_msg = "".join(lines)

            # Dividir em chunks se muito grande
            for part in split_message(status_msg):
                await message.answer(part, parse_mode=ParseMode.HTML)

        except (AttributeError, TypeError) as e:
            log.error(
                f"[cascade_status] Cascade adapter not available: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Cascade adapter não está disponível", parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[cascade_status] Invalid cascade health data: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao processar status da cascata", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[cascade_status] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao gerar status da cascata",
                parse_mode=ParseMode.HTML,
            )

    @dp.message(F.text.in_({"/bandit", "/bandit_stats"}))
    async def cmd_bandit(message: Message):
        """Status do LinUCB Cascade Bandit e progresso de aprendizado"""
        try:
            bandit = pipeline.cascade_bandit
            stats = bandit.get_stats()
            rl_stats = pipeline.get_rl_stats()

            # Progresso para ativar modo ACTIVE
            updates = stats["total_updates"]
            needed = 100
            pct = min(100, int(updates / needed * 100))
            bar_filled = int(pct / 10)
            progress_bar = "█" * bar_filled + "░" * (10 - bar_filled)

            # Divergência: quando o bandit discordaria do router
            divergences = stats["divergences"]
            predicts = stats["total_predicts"]
            div_pct = round((divergences / predicts * 100) if predicts > 0 else 0, 1)

            # Reward médio do collector
            avg_reward = (
                round(rl_stats.get("avg_reward", 0.0), 3)
                if rl_stats.get("total_events", 0) > 0
                else 0.0
            )

            # Top features aprendidas (só se tiver updates suficientes)
            features_section = ""
            if updates >= 10:
                try:
                    top = bandit.top_features_by_arm()
                    lines = []
                    for arm, feats in top.items():
                        top2 = ", ".join(f"{n}={v:+.2f}" for n, v in feats[:2])
                        lines.append(f"  <b>{arm}</b>: {top2}")
                    features_section = (
                        "\n\n<b>📐 Top features aprendidas:</b>\n" + "\n".join(lines)
                    )
                except Exception:
                    pass

            # Status de prontidão
            if stats["ready_for_active"]:
                status_line = "🟢 <b>PRONTO para modo ACTIVE</b> (A/B test 50%)"
            elif updates >= 50:
                status_line = (
                    f"🟡 Coletando ({pct}% — faltam {needed - updates} updates)"
                )
            else:
                status_line = (
                    f"🔵 Fase inicial ({pct}% — faltam {needed - updates} updates)"
                )

            msg = (
                f"<b>🤖 LinUCB Cascade Bandit</b>\n"
                f"Modo: <code>{stats['mode'].upper()}</code>\n\n"
                f"<b>📊 Progresso para A/B test:</b>\n"
                f"[{progress_bar}] {pct}% ({updates}/{needed} updates)\n"
                f"{status_line}\n\n"
                f"<b>🔍 Atividade:</b>\n"
                f"  Predições: {predicts}\n"
                f"  Divergências do router: {divergences} ({div_pct}%)\n"
                f"  Alpha (exploração): {stats['alpha']:.3f}\n"
                f"  Concorda com router: {stats['agreement_rate']:.0%}\n\n"
                f"<b>🎯 Updates por arm:</b>\n"
                f"  reflex:     {stats['updates_per_arm'].get('reflex', 0)}\n"
                f"  deliberate: {stats['updates_per_arm'].get('deliberate', 0)}\n"
                f"  deep:       {stats['updates_per_arm'].get('deep', 0)}\n\n"
                f"<b>💰 Reward médio:</b> {avg_reward:+.3f} "
                f"(eventos: {rl_stats.get('total_events', 0)})"
                f"{features_section}\n\n"
                f"<i>Shadow mode: o bandit aprende mas não interfere nas respostas ainda.</i>"
            )

            await message.answer(msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            log.error(f"[bandit] Erro ao gerar status: {e}", exc_info=True)
            await message.answer(
                "❌ Erro ao gerar status do bandit", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/recovery")
    async def cmd_recovery(message: Message):
        """Status de recuperação de erros, circuit breakers e degradação"""
        try:
            report = pipeline.error_recovery.format_recovery_report()

            # Dividir em chunks se muito grande
            for part in split_message(report):
                await message.answer(part, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[recovery] Error recovery system not configured: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de recuperação não está disponível",
                parse_mode=ParseMode.HTML,
            )
        except ValueError as e:
            log.error(
                f"[recovery] Invalid recovery data: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": "ValueError"},
            )
            await message.answer(
                "❌ Erro ao formatar relatório de recuperação",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[recovery] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar status", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/memory")
    async def cmd_memory(message: Message):
        try:
            facts = await pipeline.memory.get_facts(min_confidence=0.3, limit=20)
            if not facts:
                await message.answer(
                    "Memória vazia — ainda estou aprendendo sobre você."
                )
                return
            lines = ["<b>🧠 Memória Semântica</b>\n"]
            for f in facts:
                bar = "█" * int(f["confidence"] * 10) + "░" * (
                    10 - int(f["confidence"] * 10)
                )
                lines.append(
                    f"[{bar}] {f['confidence']:.0%} <i>({f['category']})</i>\n"
                    f"  {html.escape(f['fact'][:100])}"
                )
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
        except KeyError as e:
            log.error(
                f"[memory] Missing expected key in fact data: {e}",
                exc_info=True,
                extra={"context": "memory_command", "error_type": "KeyError"},
            )
            await message.answer(
                "❌ Erro ao recuperar memória: estrutura de dados inválida"
            )
        except (AttributeError, TypeError) as e:
            log.error(
                f"[memory] Memory service not properly configured: {e}",
                exc_info=True,
                extra={"context": "memory_command", "error_type": type(e).__name__},
            )
            await message.answer("❌ Sistema de memória não está disponível")
        except (OSError, IOError) as e:
            log.error(
                f"[memory] Database error: {e}",
                exc_info=True,
                extra={"context": "memory_command", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao acessar memória (problema com banco de dados)"
            )
        except Exception as e:
            log.critical(
                f"[memory] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "memory_command", "error_type": type(e).__name__},
            )
            await message.answer("❌ Erro inesperado ao recuperar memória")

    @dp.message(F.text == "/god")
    async def cmd_god(message: Message):
        await message.answer(
            "🔴 God Mode armado.\n"
            "Próxima mensagem será processada com profundidade máxima."
        )
        dp["god_mode_users"] = dp.get("god_mode_users", set()) | {message.from_user.id}

    @dp.message(F.text == "/rate")
    async def cmd_rate(message: Message):
        lines = ["<b>📊 PAINEL DE COTAS & LIMITES</b>\n"]
        
        # 1. Créditos Financeiros
        if hasattr(pipeline.cost_tracker, "quota_manager"):
            quotas = pipeline.cost_tracker.quota_manager.get_all_status()
            financial = [k for k, v in quotas.items() if v["type"] == "prepaid"]
            if financial:
                lines.append("<b>💰 Créditos Disponíveis</b>")
                for k in financial:
                    q = quotas[k]
                    icon = "🟢" if q["balance"] > q.get("alert_at", 1.0) else "🔴"
                    lines.append(f"  {icon} {k.capitalize()}: ${q['balance']:.2f}")
                lines.append("")

            # 2. Cotas de Busca / Mensais
            usage = [k for k, v in quotas.items() if v["type"] in ("monthly", "daily")]
            if usage:
                lines.append("<b>🔍 Cotas de Uso</b>")
                for k in usage:
                    q = quotas[k]
                    pct = (q["used"] / q["limit"]) * 100
                    bar_len = 10
                    filled = int((q["used"] / q["limit"]) * bar_len)
                    bar = "█" * filled + "░" * (bar_len - filled)
                    lines.append(f"  {k.capitalize()}: {q['used']}/{q['limit']} [{bar}] {pct:.1f}%")
                lines.append("")

        # 3. Rate Limiters (RPM)
        if _rate_limiters:
            lines.append("<b>⏱ Rate Limiters (RPM)</b>")
            for key, limiter in sorted(_rate_limiters.items()):
                if limiter.rpm > 0:
                    used = limiter.current_usage
                    total = limiter.rpm
                    bar_len = 10
                    filled = int((used / total) * bar_len) if total > 0 else 0
                    bar = "█" * filled + "░" * (bar_len - filled)
                    lines.append(f"  {key.split(':')[0]}: {used}/{total} [{bar}]")
        
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/decay")
    async def cmd_decay(message: Message):
        if not pipeline.decay_engine:
            await message.answer("Decay engine não inicializado.")
            return
        try:
            await message.answer("⏳ Rodando decay...")
            stats = await pipeline.decay_engine.run()
            await message.answer(
                f"<b>Confidence Decay</b>\n\n"
                f"  Fatos avaliados: {stats['total']}\n"
                f"  Decayed: {stats['decayed']}\n"
                f"  Removidos: {stats['removed']}\n"
                f"  Sessões limpas: {stats['sessions_cleaned']}",
                parse_mode=ParseMode.HTML,
            )
        except KeyError as e:
            log.error(
                f"[decay] Missing stats key: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": "KeyError"},
            )
            await message.answer("❌ Erro: Estatísticas de decay incompletas")
        except (RuntimeError, asyncio.TimeoutError) as e:
            log.error(
                f"[decay] Decay execution error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__},
            )
            await message.answer("❌ Erro ao executar decay. Tente novamente.")
        except Exception as e:
            log.critical(
                f"[decay] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__},
            )
            await message.answer("❌ Erro inesperado ao executar decay")

    @dp.message(F.text == "/budget")
    async def cmd_budget(message: Message):
        """Mostra resumo de gastos do dia"""
        try:
            relatorio = pipeline.cost_tracker.formatar_relatorio_custos()
            await message.answer(relatorio, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[budget] Cost tracker not available: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de custos não está disponível", parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget] Invalid cost data: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao recuperar dados de custos", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar custos", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/budget_monthly")
    async def cmd_budget_monthly(message: Message):
        """Mostra resumo de gastos do mês"""
        try:
            resumo = pipeline.cost_tracker.obter_resumo_mensal()

            linhas = ["<b>Gastos - Resumo Mensal</b>\n"]
            linhas.append(f"Mes: {resumo['mes']}")
            linhas.append(f"Total: ${resumo['custo_total']:.2f}")
            linhas.append(f"Limite: ${resumo['limite']:.2f}")
            linhas.append(f"Porcentagem: {resumo['porcentagem_limite']:.0f}%\n")

            linhas.append("<b>Por Provedor:</b>")
            for prov, custo in sorted(
                resumo["provedores"].items(), key=lambda x: x[1], reverse=True
            ):
                if custo > 0:
                    linhas.append(f"  {prov}: ${custo:.4f}")

            await message.answer("\n".join(linhas), parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[budget_monthly] Cost tracker not available: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de custos não está disponível", parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget_monthly] Invalid monthly data: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao recuperar dados mensais", parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget_monthly] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar orçamento mensal",
                parse_mode=ParseMode.HTML,
            )

    @dp.message(F.text == "/data_stats")
    async def cmd_data_stats(message: Message):
        """Mostra estatísticas do armazém de dados"""
        try:
            stats = await pipeline.data_store.estatisticas()

            linhas = ["<b>Armazem de Dados - Estatisticas</b>\n"]
            linhas.append(f"Total de fatos: {stats['total_fatos']}")
            linhas.append(f"Confianca media: {stats['confianca_media']:.2f}")
            linhas.append(f"Categorias: {len(stats['categorias'])}\n")

            linhas.append("<b>Por Categoria:</b>")
            for cat, qtd in stats["quantidade_por_categoria"].items():
                linhas.append(f"  {cat}: {qtd}")

            await message.answer("\n".join(linhas), parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[data_stats] Data store not available: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de armazenamento não está disponível",
                parse_mode=ParseMode.HTML,
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_stats] Invalid stats format: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao recuperar estatísticas", parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_stats] Data stats query timeout")
            await message.answer(
                "⏱️ Timeout ao recuperar estatísticas. Tente novamente.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[data_stats] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar estatísticas",
                parse_mode=ParseMode.HTML,
            )

    @dp.message(F.text == "/data_clean")
    async def cmd_data_clean(message: Message):
        """Executa limpeza de dados antigos"""
        try:
            await message.answer("Executando limpeza de dados...")
            resultado = await pipeline.data_gerenciador.limpar_dados(simular=False)

            linhas = ["<b>Limpeza de Dados Concluida</b>\n"]
            linhas.append(f"Total deletado: {resultado['total_deletados']}")
            linhas.append(f"  Idade maxima: {resultado['por_motivo']['idade_maxima']}")
            linhas.append(
                f"  Confianca baixa: {resultado['por_motivo']['confianca_baixa']}"
            )
            linhas.append(
                f"  Nunca utilizado: {resultado['por_motivo']['nunca_utilizado']}"
            )

            await message.answer("\n".join(linhas), parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[data_clean] Data manager not available: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de gerenciamento não está disponível",
                parse_mode=ParseMode.HTML,
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_clean] Invalid cleanup result: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao processar resultados da limpeza", parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_clean] Data cleanup timeout")
            await message.answer(
                "⏱️ Limpeza de dados está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[data_clean] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado na limpeza de dados", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/dashboard")
    async def cmd_dashboard(message: Message):
        """Mostra dashboard financeiro com status atual"""
        try:
            relatorio = await pipeline.analytics_reporter.gerar_relatorio_diario()
            await message.answer(relatorio.conteudo_html, parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[dashboard] Analytics reporter not available: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de análise não está disponível", parse_mode=ParseMode.HTML
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[dashboard] Invalid report data: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao gerar dashboard", parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[dashboard] Dashboard generation timeout")
            await message.answer(
                "⏱️ Geração de dashboard está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[dashboard] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/forecast")
    async def cmd_forecast(message: Message):
        """Mostra previsoes de custos para proximos 7 e 30 dias"""
        try:
            previsoes = await pipeline.analytics_forecaster.obter_resumo_previsoes()

            linhas = ["<b>Previsoes de Custos</b>\n"]
            linhas.append("<b>Proximos 7 Dias</b>")
            linhas.append(f"Total: ${previsoes['previsao_7d']['total']:.2f}")
            linhas.append(f"Media/Dia: ${previsoes['previsao_7d']['media_diaria']:.2f}")
            linhas.append(
                f"Range: ${previsoes['previsao_7d']['min']:.2f} - ${previsoes['previsao_7d']['max']:.2f}\n"
            )

            linhas.append("<b>Proximos 30 Dias</b>")
            linhas.append(f"Total: ${previsoes['previsao_30d']['total']:.2f}")
            linhas.append(
                f"Media/Dia: ${previsoes['previsao_30d']['media_diaria']:.2f}"
            )
            linhas.append(
                f"Range: ${previsoes['previsao_30d']['min']:.2f} - ${previsoes['previsao_30d']['max']:.2f}\n"
            )

            if previsoes["data_alerta_mensal"]:
                linhas.append("<b>Alerta de Limite</b>")
                linhas.append(f"Previsto para: {previsoes['data_alerta_mensal']}")
                linhas.append(f"Em {previsoes['dias_ate_alerta']} dias")

            await message.answer("\n".join(linhas), parse_mode=ParseMode.HTML)
        except AttributeError as e:
            log.error(
                f"[forecast] Analytics forecaster not available: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": "AttributeError"},
            )
            await message.answer(
                "❌ Sistema de previsões não está disponível", parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError, TypeError) as e:
            log.error(
                f"[forecast] Invalid forecast data: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro ao calcular previsões", parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[forecast] Forecast calculation timeout")
            await message.answer(
                "⏱️ Cálculo de previsões está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            log.critical(
                f"[forecast] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__},
            )
            await message.answer(
                "❌ Erro inesperado ao calcular previsões", parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/habits")
    async def cmd_habits(message: Message):
        afk = dp.get("afk_protocol")
        if afk and afk.habits:
            await message.answer(afk.habits.get_report(), parse_mode=ParseMode.HTML)
        else:
            await message.answer("Habit Tracker não inicializado.")

    @dp.message(F.text == "/restart")
    async def cmd_restart(message: Message):
        """Reinicia o bot manualmente"""
        await message.answer(
            "♻️ <b>Reiniciando Seeker.Bot...</b>\nO Watchdog subirá o sistema em 5s.",
            parse_mode=ParseMode.HTML
        )
        log.warning(f"Restart manual solicitado por {message.from_user.id}")
        await asyncio.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)

    @dp.callback_query(F.data == "sara_restart_yes")
    async def cb_sara_restart_yes(query: CallbackQuery):
        """Aprova restart solicitado pelo S.A.R.A."""
        await query.message.edit_text(
            "✅ <b>Restart aprovado.</b>\nReiniciando para aplicar melhorias...",
            parse_mode=ParseMode.HTML
        )
        log.info(f"S.A.R.A. Restart aprovado por {query.from_user.id}")
        await asyncio.sleep(2)
        os.kill(os.getpid(), signal.SIGTERM)
        await query.answer()

    @dp.callback_query(F.data == "sara_restart_no")
    async def cb_sara_restart_no(query: CallbackQuery):
        """Ignora restart do S.A.R.A."""
        await query.message.edit_text(
            "⏸ <b>Ignorado.</b>\nAs melhorias serão aplicadas no próximo restart natural.",
            parse_mode=ParseMode.HTML
        )
        await query.answer("Ignorado.")

    def _build_scout_keyboard(active_cats: list[str]) -> InlineKeyboardMarkup:
        keyboard = []
        for cat_key, cat_name in CATEGORY_NAMES.items():
            status = "✅" if cat_key in active_cats else "❌"
            btn = InlineKeyboardButton(
                text=f"{status} {cat_name}",
                callback_data=f"scout_toggle:{cat_key}"
            )
            keyboard.append([btn])
        return InlineKeyboardMarkup(inline_keyboard=keyboard)

    @dp.message(F.text == "/scout_config")
    async def cmd_scout_config(message: Message):
        """Configura o radar do Tech Scout"""
        scheduler = dp.get("scheduler")
        if not scheduler or "tech_scout" not in scheduler._goals:
            await message.answer("O Tech Scout não está ativo no sistema.")
            return

        scout = scheduler._goals["tech_scout"]
        keyboard = _build_scout_keyboard(scout.active_categories)
        
        await message.answer(
            "🔭 <b>Configuração do Tech Scout</b>\n\n"
            "Selecione quais áreas tecnológicas você deseja que o bot monitore:",
            reply_markup=keyboard,
            parse_mode=ParseMode.HTML
        )

    @dp.message(F.text.startswith("/switch"))
    async def cmd_switch(message: Message):
        """Alterna o provedor primário para raciocínio profundo (DEEP)."""
        args = message.text.split()
        if len(args) < 2:
            await message.answer(
                "🛸 <b>Seletor de Cérebro</b>\n\n"
                "Uso: <code>/switch kimi</code> ou <code>/switch deepseek</code>\n\n"
                "Isso altera qual API o Seeker usa para tarefas complexas.",
                parse_mode=ParseMode.HTML
            )
            return

        target = args[1].lower()
        # Mapeia apelidos
        provider_map = {
            "kimi": "kimi",
            "moonshot": "kimi",
            "deepseek": "deepseek",
            "ds": "deepseek"
        }
        
        provider = provider_map.get(target)
        if not provider:
            await message.answer(f"❌ Provedor '{target}' não reconhecido.")
            return

        from config.models import CognitiveRole
        success = pipeline.model_router.move_to_primary(CognitiveRole.DEEP, provider)
        
        if success:
            await message.answer(
                f"✅ <b>Cérebro alterado!</b>\n"
                f"Agora o Seeker usará <b>{provider.capitalize()}</b> como motor primário para análises profundas.",
                parse_mode=ParseMode.HTML
            )
            log.info(f"Provedor DEEP alterado para {provider} por {message.from_user.id}")
        else:
            await message.answer(f"❌ Não foi possível ativar {provider}. Verifique se ele está configurado como fallback.")

    @dp.callback_query(F.data.startswith("scout_toggle:"))
    async def cb_scout_toggle(query: CallbackQuery):
        cat_key = query.data.split(":")[1]
        
        scheduler = dp.get("scheduler")
        if not scheduler or "tech_scout" not in scheduler._goals:
            await query.answer("Erro: Tech Scout inativo.")
            return
            
        scout = scheduler._goals["tech_scout"]
        
        if cat_key in scout.active_categories:
            scout.active_categories.remove(cat_key)
        else:
            scout.active_categories.append(cat_key)
            
        # Opcional: forçar um save_state explícito no scheduler
        await scheduler._save_state()
        
        keyboard = _build_scout_keyboard(scout.active_categories)
        await query.message.edit_reply_markup(reply_markup=keyboard)
        await query.answer(f"Categoria {'ativada' if cat_key in scout.active_categories else 'desativada'}.")

    # ── RL: Explicit Feedback Command (Phase 2 Integration) ──
    @dp.message(F.text.startswith("/feedback"))
    async def cmd_feedback(message: Message):
        """
        Explicit feedback command: /feedback <value> [reason]
        value: -1 (bad), 0 (neutral), +1 (good)
        reason: optional explanation
        """
        # Parse command: /feedback -1 "motivo"
        match = re.match(r"/feedback\s+([+-]?[01])\s*(.*)$", message.text or "")
        if not match:
            await message.answer(
                "❌ Uso: <code>/feedback &lt;-1|0|+1&gt; [motivo]</code>\n"
                "Exemplos:\n"
                "  /feedback +1\n"
                "  /feedback -1 \"muito longo\"\n"
                "  /feedback 0 \"parcialmente correto\""
            )
            return

        value_str, reason = match.groups()
        value = float(value_str)
        reason = reason.strip().strip('"\'') or "feedback explícito via /feedback"

        # Get last decision_id from message controller state
        if not hasattr(pipeline, '_message_controller'):
            await message.answer("⚠️ Erro: Message controller não inicializado.")
            return

        controller = pipeline._message_controller
        if not hasattr(controller, '_rl_state'):
            await message.answer("⚠️ Nenhuma resposta anterior a avaliar.")
            return

        last_rl = controller._rl_state.get(message.chat.id)
        if not last_rl:
            await message.answer("⚠️ Nenhuma resposta anterior a avaliar.")
            return

        decision_id = last_rl["decision_id"]
        try:
            pipeline.reward_collector.record_explicit_feedback(
                decision_id=decision_id,
                value=value,
                reason=reason,
            )
            emoji_map = {-1: "👎", 0: "😐", 1: "👍"}
            await message.answer(
                f"{emoji_map.get(int(value), '❓')} Feedback registrado!\n"
                f"Valor: {value:+.1f} | Motivo: {reason}"
            )
            log.info(f"[feedback] Chat {message.chat.id}: value={value}, reason={reason}")
        except Exception as e:
            log.error(f"[feedback] Erro ao registrar: {e}")
            await message.answer(f"❌ Erro ao registrar feedback: {e}")

    # ── RL: Feedback Button Callback (Inline Button) ──
    @dp.callback_query(F.data.startswith("fb:"))
    async def cb_feedback_button(query: CallbackQuery):
        """Handle feedback button clicks: fb:<value>:<decision_id>"""
        try:
            parts = query.data.split(":")
            if len(parts) != 3:
                await query.answer("❌ Dado inválido", show_alert=False)
                return

            value_str, decision_id = parts[1], parts[2]
            value = float(value_str)

            pipeline.reward_collector.record_explicit_feedback(
                decision_id=decision_id,
                value=value,
                reason="feedback via botão inline",
            )

            emoji_map = {-1: "👎", 0: "😐", 1: "👍"}
            await query.answer(f"{emoji_map.get(int(value), '❓')} Feedback registrado!", show_alert=False)
            log.info(f"[feedback] Botão clicado: value={value}, decision_id={decision_id[:8]}")
        except Exception as e:
            log.error(f"[feedback] Erro ao processar botão: {e}")
            await query.answer(f"❌ Erro: {e}", show_alert=True)

    # ── RL: Weight Fine-tuning Command (Phase 2) ──
    @dp.message(F.text.startswith("/rl_tune"))
    async def cmd_rl_tune(message: Message):
        """
        RL weight fine-tuning command.
        Usage: /rl_tune <behavior%> <technical%>
        Example: /rl_tune 70 30 (default), /rl_tune 60 40 (more technical)
        Status: /rl_tune status
        """
        text = message.text or ""

        # Handle status subcommand
        if "status" in text.lower():
            weights_info = pipeline.reward_collector.format_weights()
            await message.answer(weights_info, parse_mode=ParseMode.HTML)
            return

        # Parse /rl_tune <behavior%> <technical%>
        match = re.match(r"/rl_tune\s+(\d+)\s+(\d+)\s*$", text)
        if not match:
            await message.answer(
                "❌ Uso: <code>/rl_tune &lt;behavior%&gt; &lt;technical%&gt;</code>\n"
                "Exemplo: <code>/rl_tune 70 30</code> (padrão)\n"
                "Ou: <code>/rl_tune status</code> para ver pesos atuais"
            )
            return

        behav_pct, tech_pct = int(match.group(1)), int(match.group(2))
        behav = behav_pct / 100.0
        tech = tech_pct / 100.0

        if pipeline.reward_collector.set_weights(behav, tech):
            weights_info = pipeline.reward_collector.format_weights()
            await message.answer(
                f"✅ Pesos ajustados!\n\n{weights_info}",
                parse_mode=ParseMode.HTML
            )
            log.info(f"[rl_tune] Chat {message.chat.id}: behavior={behav_pct}%, technical={tech_pct}%")
        else:
            await message.answer(
                f"❌ Pesos inválidos! Devem somar 100%: {behav_pct}% + {tech_pct}% = {behav_pct + tech_pct}%"
            )

    # ── RL: Bandit Mode Activation Commands (Phase 2) ──
    @dp.message(F.text == "/rl_activate")
    async def cmd_rl_activate(message: Message):
        """
        Manually force bandit activation (god mode only).
        Transitions from SHADOW to ACTIVE mode for A/B testing.
        """
        # Check god mode
        god_users = getattr(pipeline._message_controller, '_god_mode_users', set())
        if message.from_user.id not in god_users:
            await message.answer("❌ Este comando requer god mode.")
            return

        from src.core.rl.bandits.cascade import BanditMode

        stats_before = pipeline.cascade_bandit.get_stats()
        was_activated = pipeline.cascade_bandit.set_mode(BanditMode.ACTIVE)

        if was_activated:
            await message.answer(
                f"✅ Bandit ATIVADO manualmente!\n\n"
                f"<b>Before:</b> {stats_before['mode'].upper()}\n"
                f"<b>After:</b> ACTIVE\n"
                f"Agreement: {stats_before['agreement_rate']:.0%}\n"
                f"Updates: {stats_before['total_updates']}\n"
                f"Alpha: {stats_before['alpha']:.3f}",
                parse_mode=ParseMode.HTML
            )
            log.info(f"[rl_activate] Chat {message.chat.id}: manually activated bandit")
        else:
            await message.answer(
                f"ℹ️ Bandit já está em modo {stats_before['mode'].upper()}."
            )

    @dp.message(F.text == "/rl_deactivate")
    async def cmd_rl_deactivate(message: Message):
        """
        Manually revert bandit to SHADOW mode (god mode only).
        Returns to safe logging-only mode.
        """
        # Check god mode
        god_users = getattr(pipeline._message_controller, '_god_mode_users', set())
        if message.from_user.id not in god_users:
            await message.answer("❌ Este comando requer god mode.")
            return

        from src.core.rl.bandits.cascade import BanditMode

        stats_before = pipeline.cascade_bandit.get_stats()
        was_deactivated = pipeline.cascade_bandit.set_mode(BanditMode.SHADOW)

        if was_deactivated:
            await message.answer(
                f"✅ Bandit revertido para SHADOW!\n\n"
                f"<b>Before:</b> {stats_before['mode'].upper()}\n"
                f"<b>After:</b> SHADOW\n"
                f"Agreement: {stats_before['agreement_rate']:.0%}\n"
                f"Updates: {stats_before['total_updates']}",
                parse_mode=ParseMode.HTML
            )
            log.info(f"[rl_deactivate] Chat {message.chat.id}: manually deactivated bandit")
        else:
            await message.answer(
                f"ℹ️ Bandit já está em modo {stats_before['mode'].upper()}."
            )

    @dp.message(F.text == "/rl_stats")
    async def cmd_rl_stats(message: Message):
        """Dashboard completo de RL: bandit convergência + pesos de reward."""
        bandit = getattr(pipeline, "cascade_bandit", None)
        reward = getattr(pipeline, "reward_collector", None)

        lines = ["<b>Seeker.Bot — RL Dashboard</b>\n"]

        # ── Bandit stats ──────────────────────────────────────────────────────
        if bandit is not None:
            s = bandit.get_stats()
            mode_emoji = {"shadow": "👁", "active": "⚡", "full": "🚀"}.get(s["mode"], "?")
            lines.append(f"<b>LinUCB Bandit</b> {mode_emoji} <code>{s['mode'].upper()}</code>")

            # Convergência
            bar_len = 20
            filled = int(s["agreement_rate"] * bar_len)
            bar = "█" * filled + "░" * (bar_len - filled)
            lines.append(f"Concordância: [{bar}] {s['agreement_rate']:.0%}")

            # Threshold 70% indicator
            threshold_pos = int(0.70 * bar_len)
            threshold_bar = " " * threshold_pos + "▲" + " " * (bar_len - threshold_pos)
            lines.append(f"              {threshold_bar} 70%")

            lines.append(
                f"Updates: {s['total_updates']} | Predições: {s['total_predicts']} | "
                f"Divergências: {s['divergences']}"
            )
            lines.append(f"Alpha: {s['alpha']:.3f}")

            # Updates por arm
            lines.append("\n<b>Updates por arm:</b>")
            total_arm = sum(s["updates_per_arm"].values()) or 1
            for arm, n in s["updates_per_arm"].items():
                pct = n / total_arm
                arm_bar = "█" * int(pct * 10) + "░" * (10 - int(pct * 10))
                lines.append(f"  {arm:<12} [{arm_bar}] {n} ({pct:.0%})")

            # Status / próximo passo
            if s["mode"] == "active":
                lines.append("\n⚡ <b>A/B test ativo</b> — 50% das queries via bandit")
            elif s["mode"] == "full":
                lines.append("\n🚀 <b>Modo FULL</b> — bandit substitui o router")
            elif s["ready_for_active"]:
                lines.append("\n✅ <b>Pronto para ACTIVE</b> — use <code>/rl_activate</code>")
            else:
                remaining = max(0, 100 - s["total_updates"])
                lines.append(f"\n⏳ Coletando dados: faltam {remaining} updates para threshold")
        else:
            lines.append("⚠️ Bandit não inicializado")

        # ── Reward weights ────────────────────────────────────────────────────
        if reward is not None:
            lines.append("")
            lines.append(reward.format_weights())
        else:
            lines.append("\n⚠️ RewardCollector não disponível")

        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
