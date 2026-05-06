import logging
from aiogram import Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode
import html
import asyncio
from config.models import CognitiveRole
from src.core.pipeline import SeekerPipeline
from src.providers.base import _rate_limiters
from src.channels.telegram.formatter import split_message

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
        lines.append(f"\n<b>Providers na arbitragem:</b>")
        for m in router.get_all_for_arbitrage():
            lines.append(f"  → {m.display_name} ({m.provider})")
        try:
            stats = await pipeline.memory.get_episode_stats()
            facts = await pipeline.memory.get_facts(limit=999)
            lines.append(f"\n<b>Memória:</b>")
            lines.append(f"  {stats['total_episodes']} episódios | {len(facts)} fatos")
            lines.append(f"  Custo acumulado: ${stats['total_cost_usd']:.4f}")
            if stats['avg_latency_ms']:
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
                    lines.append(f"\n<b>🔄 OODA Loop:</b>")
                    lines.append(f"  {ooda_stats['total_iterations']} iterações")
                    lines.append(
                        f"  Success rate: {ooda_stats['success_rate']:.0%} "
                        f"| Bloqueadas: {ooda_stats['blocked_count']}"
                    )
                    lines.append(f"  Latência média: {ooda_stats['avg_latency_ms']:.0f}ms")

        except Exception:
            lines.append(f"\n<b>Memória:</b> inicializando...")
        await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)

    @dp.message(F.text == "/saude")
    async def cmd_saude(message: Message):
        try:
            scheduler = dp.get("scheduler")
            if not scheduler:
                await message.answer("❌ Goal scheduler não inicializado.", parse_mode=ParseMode.HTML)
                return

            dashboard = scheduler.get_health_dashboard()
            lines = ["<b>📊 Health Dashboard dos Goals</b>\n"]

            # Global summary
            lines.append(f"<b>🌍 Global:</b>")
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
            lines.append(f"\n<b>💰 Budget Global:</b> {emoji} ${spent:.4f}/${limit} ({pct:.0f}%)")

            # Per-goal metrics
            lines.append(f"\n<b>📈 Goals Detalhados:</b>")
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
                budget_pct = budget["spent_today"] / budget["limit"] * 100 if budget["limit"] > 0 else 0
                budget_emoji = "🔴" if budget_pct > 80 else ("🟡" if budget_pct > 50 else "🟢")
                lines.append(f"    {budget_emoji} Budget: ${budget['spent_today']:.4f}/${budget['limit']} ({budget_pct:.0f}%)")

            # Friction metrics
            friction = dashboard["friction_metrics"]
            if sum(friction.values()) > 0:
                lines.append(f"\n<b>🛡️ Fricção Controlada:</b>")
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
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Goal scheduler não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[saude] Invalid health dashboard data: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar dados de saúde",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[saude] Unexpected error in health dashboard: {e}",
                exc_info=True,
                extra={"context": "health_dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard de saúde",
                parse_mode=ParseMode.HTML
            )

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
                extra={"context": "perf_report", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de performance não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[perf] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao gerar relatório de performance",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[perf] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao gerar relatório",
                parse_mode=ParseMode.HTML
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
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Dashboard de performance não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[perf_detailed] Invalid performance data: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar métricas de performance",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[perf_detailed] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "perf_detailed", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar métricas detalhadas",
                parse_mode=ParseMode.HTML
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
            lines.append(f"Savings vs NIM: {cost_analysis['estimated_savings_vs_nim']}\n")

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
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Cascade adapter não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[cascade_status] Invalid cascade health data: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar status da cascata",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[cascade_status] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "cascade_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao gerar status da cascata",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text.in_({"/bandit", "/bandit_stats"}))
    async def cmd_bandit(message: Message):
        """Status do LinUCB Cascade Bandit e progresso de aprendizado"""
        try:
            bandit = pipeline.cascade_bandit
            stats  = bandit.get_stats()
            rl_stats = pipeline.get_rl_stats()

            # Progresso para ativar modo ACTIVE
            updates = stats["total_updates"]
            needed  = 100
            pct     = min(100, int(updates / needed * 100))
            bar_filled = int(pct / 10)
            progress_bar = "█" * bar_filled + "░" * (10 - bar_filled)

            # Divergência: quando o bandit discordaria do router
            divergences = stats["divergences"]
            predicts    = stats["total_predicts"]
            div_pct     = round((divergences / predicts * 100) if predicts > 0 else 0, 1)

            # Reward médio do collector
            avg_reward = round(rl_stats.get("avg_reward", 0.0), 3) if rl_stats.get("total_events", 0) > 0 else 0.0

            # Top features aprendidas (só se tiver updates suficientes)
            features_section = ""
            if updates >= 10:
                try:
                    top = bandit.top_features_by_arm()
                    lines = []
                    for arm, feats in top.items():
                        top2 = ", ".join(f"{n}={v:+.2f}" for n, v in feats[:2])
                        lines.append(f"  <b>{arm}</b>: {top2}")
                    features_section = "\n\n<b>📐 Top features aprendidas:</b>\n" + "\n".join(lines)
                except Exception:
                    pass

            # Status de prontidão
            if stats["ready_for_active"]:
                status_line = "🟢 <b>PRONTO para modo ACTIVE</b> (A/B test 50%)"
            elif updates >= 50:
                status_line = f"🟡 Coletando ({pct}% — faltam {needed - updates} updates)"
            else:
                status_line = f"🔵 Fase inicial ({pct}% — faltam {needed - updates} updates)"

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
            await message.answer("❌ Erro ao gerar status do bandit", parse_mode=ParseMode.HTML)

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
                extra={"context": "recovery_status", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de recuperação não está disponível",
                parse_mode=ParseMode.HTML
            )
        except ValueError as e:
            log.error(
                f"[recovery] Invalid recovery data: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": "ValueError"}
            )
            await message.answer(
                "❌ Erro ao formatar relatório de recuperação",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[recovery] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "recovery_status", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar status",
                parse_mode=ParseMode.HTML
            )
    @dp.message(F.text == "/memory")
    async def cmd_memory(message: Message):
        try:
            facts = await pipeline.memory.get_facts(min_confidence=0.3, limit=20)
            if not facts:
                await message.answer("Memória vazia — ainda estou aprendendo sobre você.")
                return
            lines = ["<b>🧠 Memória Semântica</b>\n"]
            for f in facts:
                bar = "█" * int(f['confidence'] * 10) + "░" * (10 - int(f['confidence'] * 10))
                lines.append(
                    f"[{bar}] {f['confidence']:.0%} <i>({f['category']})</i>\n"
                    f"  {html.escape(f['fact'][:100])}"
                )
            await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
        except KeyError as e:
            log.error(f"[memory] Missing expected key in fact data: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": "KeyError"})
            await message.answer("❌ Erro ao recuperar memória: estrutura de dados inválida")
        except (AttributeError, TypeError) as e:
            log.error(f"[memory] Memory service not properly configured: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": type(e).__name__})
            await message.answer("❌ Sistema de memória não está disponível")
        except (OSError, IOError) as e:
            log.error(f"[memory] Database error: {e}", exc_info=True,
                      extra={"context": "memory_command", "error_type": type(e).__name__})
            await message.answer("❌ Erro ao acessar memória (problema com banco de dados)")
        except Exception as e:
            log.critical(f"[memory] Unexpected error: {e}", exc_info=True,
                         extra={"context": "memory_command", "error_type": type(e).__name__})
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
        if not _rate_limiters:
            await message.answer("Nenhum rate limiter ativo ainda.")
            return
        lines = ["<b>⏱ Rate Limiters</b>\n"]
        for key, limiter in sorted(_rate_limiters.items()):
            if limiter.rpm <= 0:
                lines.append(f"  <b>{key}</b>: sem limite")
            else:
                used = limiter.current_usage
                total = limiter.rpm
                bar_len = 15
                filled = int((used / total) * bar_len) if total > 0 else 0
                bar = "█" * filled + "░" * (bar_len - filled)
                lines.append(f"  <b>{key.split(':')[0]}</b>")
                lines.append(f"  [{bar}] {used}/{total} RPM")
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
                extra={"context": "decay_cleanup", "error_type": "KeyError"}
            )
            await message.answer(
                "❌ Erro: Estatísticas de decay incompletas"
            )
        except (RuntimeError, asyncio.TimeoutError) as e:
            log.error(
                f"[decay] Decay execution error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao executar decay. Tente novamente."
            )
        except Exception as e:
            log.critical(
                f"[decay] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "decay_cleanup", "error_type": type(e).__name__}
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
                extra={"context": "budget_report", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de custos não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget] Invalid cost data: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar dados de custos",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_report", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar custos",
                parse_mode=ParseMode.HTML
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
                resumo['provedores'].items(),
                key=lambda x: x[1],
                reverse=True
            ):
                if custo > 0:
                    linhas.append(f"  {prov}: ${custo:.4f}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[budget_monthly] Cost tracker not available: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de custos não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError) as e:
            log.error(
                f"[budget_monthly] Invalid monthly data: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar dados mensais",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[budget_monthly] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "budget_monthly", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar orçamento mensal",
                parse_mode=ParseMode.HTML
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
            for cat, qtd in stats['quantidade_por_categoria'].items():
                linhas.append(f"  {cat}: {qtd}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[data_stats] Data store not available: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de armazenamento não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_stats] Invalid stats format: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao recuperar estatísticas",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_stats] Data stats query timeout")
            await message.answer(
                "⏱️ Timeout ao recuperar estatísticas. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[data_stats] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_stats", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao recuperar estatísticas",
                parse_mode=ParseMode.HTML
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
            linhas.append(f"  Confianca baixa: {resultado['por_motivo']['confianca_baixa']}")
            linhas.append(f"  Nunca utilizado: {resultado['por_motivo']['nunca_utilizado']}")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[data_clean] Data manager not available: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de gerenciamento não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, TypeError) as e:
            log.error(
                f"[data_clean] Invalid cleanup result: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao processar resultados da limpeza",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[data_clean] Data cleanup timeout")
            await message.answer(
                "⏱️ Limpeza de dados está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[data_clean] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "data_cleanup", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado na limpeza de dados",
                parse_mode=ParseMode.HTML
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
                extra={"context": "dashboard", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de análise não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (ValueError, KeyError) as e:
            log.error(
                f"[dashboard] Invalid report data: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao gerar dashboard",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[dashboard] Dashboard generation timeout")
            await message.answer(
                "⏱️ Geração de dashboard está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[dashboard] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "dashboard", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao carregar dashboard",
                parse_mode=ParseMode.HTML
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
            linhas.append(f"Range: ${previsoes['previsao_7d']['min']:.2f} - ${previsoes['previsao_7d']['max']:.2f}\n")

            linhas.append("<b>Proximos 30 Dias</b>")
            linhas.append(f"Total: ${previsoes['previsao_30d']['total']:.2f}")
            linhas.append(f"Media/Dia: ${previsoes['previsao_30d']['media_diaria']:.2f}")
            linhas.append(f"Range: ${previsoes['previsao_30d']['min']:.2f} - ${previsoes['previsao_30d']['max']:.2f}\n")

            if previsoes['data_alerta_mensal']:
                linhas.append("<b>Alerta de Limite</b>")
                linhas.append(f"Previsto para: {previsoes['data_alerta_mensal']}")
                linhas.append(f"Em {previsoes['dias_ate_alerta']} dias")

            await message.answer(
                "\n".join(linhas),
                parse_mode=ParseMode.HTML
            )
        except AttributeError as e:
            log.error(
                f"[forecast] Analytics forecaster not available: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": "AttributeError"}
            )
            await message.answer(
                "❌ Sistema de previsões não está disponível",
                parse_mode=ParseMode.HTML
            )
        except (KeyError, ValueError, TypeError) as e:
            log.error(
                f"[forecast] Invalid forecast data: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro ao calcular previsões",
                parse_mode=ParseMode.HTML
            )
        except asyncio.TimeoutError:
            log.warning("[forecast] Forecast calculation timeout")
            await message.answer(
                "⏱️ Cálculo de previsões está demorando. Tente novamente.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            log.critical(
                f"[forecast] Unexpected error: {e}",
                exc_info=True,
                extra={"context": "forecast", "error_type": type(e).__name__}
            )
            await message.answer(
                "❌ Erro inesperado ao calcular previsões",
                parse_mode=ParseMode.HTML
            )

    @dp.message(F.text == "/habits")
    async def cmd_habits(message: Message):
        afk = dp.get("afk_protocol")
        if afk and afk.habits:
            await message.answer(afk.habits.get_report(), parse_mode=ParseMode.HTML)
        else:
            await message.answer("Habit Tracker não inicializado.")
