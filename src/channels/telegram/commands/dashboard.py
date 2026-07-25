import logging
import os
import json
import time
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, List

from aiogram import Router
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram import Dispatcher

from src.channels.telegram.formatter import split_message
from src.core.pipeline import SeekerPipeline

logger = logging.getLogger(__name__)

router = Router()
_pipeline: SeekerPipeline | None = None


def _format_number(num: float | int, decimal: int = 0) -> str:
    """Format number with thousands separator."""
    if isinstance(num, float):
        return f"{num:,.{decimal}f}"
    return f"{num:,}"


def _format_cost(cost: float) -> str:
    """Format cost with $ sign and proper decimals."""
    return f"${cost:,.4f}"


def _progress_bar(ratio: float, width: int = 10) -> str:
    """Create a text-based progress bar."""
    filled = int(ratio * width)
    empty = width - filled
    return "█" * filled + "░" * empty


def _get_file_json(filepath: str) -> Optional[Dict]:
    """Safely read a JSON file, return None on error."""
    try:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to read {filepath}: {e}")
    return None


@router.message(Command("dashboard"))
async def cmd_dashboard(message: Message):
    """Comprehensive system dashboard aggregating all subsystems."""
    global _pipeline
    pipeline = _pipeline
    if pipeline is None:
        await message.answer("⚠️ Pipeline não inicializado ainda.")
        return
    try:
        dashboard_text = await _build_dashboard(pipeline)
        
        for chunk in split_message(dashboard_text, max_length=4000):
            await message.answer(chunk, parse_mode=ParseMode.HTML)
            
    except AttributeError as e:
        logger.error(f"AttributeError in dashboard: {e}")
        await message.answer("⚠️ Erro ao acessar componentes do sistema. Tente novamente.")
    except ValueError as e:
        logger.error(f"ValueError in dashboard: {e}")
        await message.answer("⚠️ Erro de dados no sistema. Tente novamente.")
    except Exception as e:
        logger.error(f"Unexpected error in dashboard: {e}", exc_info=True)
        await message.answer("⚠️ Erro inesperado ao gerar dashboard. Tente novamente.")


async def _build_dashboard(pipeline: SeekerPipeline) -> str:
    """Build the comprehensive dashboard text."""
    lines = []
    lines.append("📊 <b>SEEKER.BOT DASHBOARD</b>")
    lines.append(f"⏰ Atualizado: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    lines.append("")
    
    lines.extend(await _build_system_health(pipeline))
    lines.extend(await _build_rl_bandit(pipeline))
    lines.extend(await _build_knowledge_graph(pipeline))
    lines.extend(await _build_cascade_costs(pipeline))
    lines.extend(await _build_circuit_breakers(pipeline))
    lines.extend(await _build_quotas(pipeline))
    lines.extend(await _build_performance(pipeline))
    
    lines.append("")
    lines.append("─" * 40)
    lines.append("✅ Dashboard gerado com sucesso")
    
    return "\n".join(lines)


async def _build_system_health(pipeline: SeekerPipeline) -> List[str]:
    """Build System Health section."""
    lines = ["🏥 <b>SISTEMA</b>"]
    
    try:
        import psutil
        process = psutil.Process()
        mem_info = process.memory_info()
        mem_mb = mem_info.rss / 1024 / 1024
        mem_percent = process.memory_percent()
        lines.append(f"  💾 Memória: {mem_mb:.1f}MB ({mem_percent:.1f}%) {_progress_bar(mem_percent/100)}")
    except Exception:
        lines.append("  💾 Memória: N/A")
    
    try:
        session_count = 0
        if hasattr(pipeline, 'memory') and pipeline.memory:
            session_count = getattr(pipeline.memory, 'session_count', 0) or 0
        lines.append(f"  👥 Sessões ativas: {_format_number(session_count)}")
    except Exception:
        lines.append("  👥 Sessões ativas: N/A")
    
    try:
        oorda_stats = ""
        if hasattr(pipeline, 'analytics_dashboard') and pipeline.analytics_dashboard:
            oorda_stats = getattr(pipeline.analytics_dashboard, 'ooda_stats', {}) or {}
        if isinstance(oorda_stats, dict):
            cycles = oorda_stats.get('cycles', oorda_stats.get('total_cycles', 0))
            lines.append(f"  🔄 OODA loops: {_format_number(cycles)}")
        else:
            lines.append("  🔄 OODA loops: 0")
    except Exception:
        lines.append("  🔄 OODA loops: N/A")
    
    try:
        goal_health = "✅"
        if hasattr(pipeline, 'decay_engine') and pipeline.decay_engine:
            last_run = getattr(pipeline.decay_engine, 'last_run', None)
            if last_run:
                age = (datetime.now() - last_run).total_seconds()
                if age > 3600:
                    goal_health = "⚠️"
        lines.append(f"  🎯 Goal Engine: {goal_health} OK")
    except Exception:
        lines.append("  🎯 Goal Engine: N/A")
    
    lines.append("")
    return lines


async def _build_rl_bandit(pipeline: SeekerPipeline) -> List[str]:
    """Build RL Bandit section."""
    lines = ["🎰 <b>RL BANDIT</b>"]
    
    try:
        if hasattr(pipeline, 'cascade_bandit') and pipeline.cascade_bandit:
            stats = pipeline.cascade_bandit.get_stats()
            if isinstance(stats, dict):
                mode = stats.get('mode', 'N/A')
                alpha = stats.get('alpha', 0.0)
                agreement = stats.get('agreement_rate', 0.0)
                updates = stats.get('updates_per_arm', {})
                ready = stats.get('ready_for_active', False)
                
                lines.append(f"  ⚙️  Modo: {mode}")
                lines.append(f"  α(alpha): {alpha:.4f}")
                lines.append(f"  📈 Agreement Rate: {agreement*100:.1f}% {_progress_bar(agreement)}")
                lines.append(f"  ✅ Ready for Active: {'Sim' if ready else 'Não'}")
                
                if updates:
                    total_updates = sum(updates.values()) if isinstance(updates, dict) else 0
                    lines.append(f"  🔢 Total updates: {_format_number(total_updates)}")
        else:
            lines.append("  ⚙️  Modo: N/A")
            lines.append("  α(alpha): N/A")
    except Exception as e:
        logger.warning(f"Error building RL Bandit section: {e}")
        lines.append("  ⚙️  RL Bandit: Erro ao acessar")
    
    lines.append("")
    return lines


async def _build_knowledge_graph(pipeline: SeekerPipeline) -> List[str]:
    """Build Knowledge Graph section."""
    lines = ["🧠 <b>KNOWLEDGE GRAPH</b>"]
    
    try:
        kg_stats = {}
        if hasattr(pipeline, 'analytics_dashboard') and pipeline.analytics_dashboard:
            kg_stats = getattr(pipeline.analytics_dashboard, 'kg_stats', {}) or {}
        
        if not kg_stats:
            graph_data = _get_file_json("data/knowledge_graph.json")
            if graph_data:
                kg_stats = graph_data
        
        fact_count = kg_stats.get('fact_count', kg_stats.get('facts', 0))
        episodic = kg_stats.get('episodic_count', kg_stats.get('episodic', 0))
        entities = kg_stats.get('entities', 0)
        triplas = kg_stats.get('triplas', kg_stats.get('relationships', 0))
        events = kg_stats.get('events', 0)
        leads = kg_stats.get('leads', 0)
        
        lines.append(f"  📝 Fatos: {_format_number(fact_count)}")
        lines.append(f"  💭 Episódicos: {_format_number(episodic)}")
        lines.append(f"  👤 Entidades: {_format_number(entities)}")
        lines.append(f"  🔗 Tríplas: {_format_number(triplas)}")
        lines.append(f"  📅 Eventos: {_format_number(events)}")
        lines.append(f"  🎯 Leads: {_format_number(leads)}")
    except Exception as e:
        logger.warning(f"Error building Knowledge Graph section: {e}")
        lines.append("  🧠 Knowledge Graph: Erro ao acessar")
    
    lines.append("")
    return lines


async def _build_cascade_costs(pipeline: SeekerPipeline) -> List[str]:
    """Build Cascade / Costs section."""
    lines = ["💰 <b>CUSTOS</b>"]
    
    try:
        today_cost = 0.0
        month_cost = 0.0
        budget_percent = 0.0
        provider_breakdown = {}
        
        if hasattr(pipeline, 'cost_tracker') and pipeline.cost_tracker:
            tracker = pipeline.cost_tracker
            today_cost = getattr(tracker, 'today_cost', 0.0) or 0.0
            month_cost = getattr(tracker, 'month_cost', 0.0) or 0.0
            budget = getattr(tracker, 'monthly_budget', 1000.0) or 1000.0
            budget_percent = (month_cost / budget * 100) if budget > 0 else 0.0
            provider_breakdown = getattr(tracker, 'provider_costs', {}) or {}
        else:
            costs_data = _get_file_json("data/costs.json")
            if costs_data:
                today_cost = costs_data.get('today_cost', 0.0)
                month_cost = costs_data.get('month_cost', 0.0)
                budget_percent = costs_data.get('budget_percent', 0.0)
                provider_breakdown = costs_data.get('provider_breakdown', {})
        
        lines.append(f"  📅 Hoje: {_format_cost(today_cost)}")
        lines.append(f"  📆 Mês: {_format_cost(month_cost)}")
        lines.append(f"  💵 Budget: {budget_percent:.1f}% {_progress_bar(min(budget_percent/100, 1.0))}")
        
        if provider_breakdown:
            for provider, cost in sorted(provider_breakdown.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"    • {provider}: {_format_cost(cost)}")
    except Exception as e:
        logger.warning(f"Error building Costs section: {e}")
        lines.append("  💰 Custos: Erro ao acessar")
    
    lines.append("")
    return lines


async def _build_circuit_breakers(pipeline: SeekerPipeline) -> List[str]:
    """Build Circuit Breakers section."""
    lines = ["🔌 <b>CIRCUIT BREAKERS</b>"]
    
    try:
        rate_limits = _get_file_json("data/rate_limits.json")
        
        breakers = [
            ('tavily', '🌐 Tavily'),
            ('brave', '🦁 Brave'),
            ('duckduckgo', '🦆 DuckDuckGo'),
        ]
        
        for key, name in breakers:
            if rate_limits and key in rate_limits:
                data = rate_limits[key]
                failures = data.get('failures', 0)
                cooldown = data.get('cooldown_until', None)
                in_cooldown = False
                if cooldown:
                    try:
                        cooldown_dt = datetime.fromisoformat(cooldown)
                        in_cooldown = cooldown_dt > datetime.now()
                    except Exception:
                        pass
                
                status = "✅" if failures == 0 else "⚠️" if failures < 5 else "🔴"
                if in_cooldown:
                    status = "❄️"
                
                lines.append(f"  {status} {name}: {failures} falhas")
                if in_cooldown:
                    lines.append(f"      ❄️ Em cooldown")
            else:
                lines.append(f"  ✅ {name}: OK")
    
    except Exception as e:
        logger.warning(f"Error building Circuit Breakers section: {e}")
        lines.append("  🔌 Circuit Breakers: Erro ao acessar")
    
    lines.append("")
    return lines


async def _build_quotas(pipeline: SeekerPipeline) -> List[str]:
    """Build Quotas section."""
    lines = ["📦 <b>QUOTAS</b>"]
    
    try:
        quotas = _get_file_json("data/quotas.json")
        
        quota_items = [
            ('tavily', '🔍 Tavily', 1000),
            ('brave', '🦁 Brave', 1000),
            ('deepseek', '💎 DeepSeek', None),
            ('gemini', '✨ Gemini', 500),
        ]
        
        for key, name, limit in quota_items:
            if quotas and key in quotas:
                data = quotas[key]
                used = data.get('used', 0)
                remaining = data.get('remaining', 0)
                cost = data.get('cost', 0.0)
                
                if limit:
                    pct = (used / limit * 100) if limit > 0 else 0
                    lines.append(f"  {name}: {used}/{limit} ({pct:.1f}%)")
                    lines.append(f"      {_progress_bar(pct/100)} Restante: {remaining}")
                else:
                    if cost is not None:
                        lines.append(f"  {name}: {_format_cost(cost)}")
                    else:
                        lines.append(f"  {name}: {used} usado")
            else:
                lines.append(f"  {name}: N/A")
    
    except Exception as e:
        logger.warning(f"Error building Quotas section: {e}")
        lines.append("  📦 Quotas: Erro ao acessar")
    
    lines.append("")
    return lines


    """Build ViralX9 section."""
    lines = ["🚀 <b>VIRALX9</b>"]
    
    try:
        
            
            lines.append(f"  🔄 Ciclos realizados: {_format_number(ciclos)}")
            lines.append(f"  ✅ Nichos ativos: {nichos_ativos}")
            lines.append(f"  ⏸️  Nichos pausados: {nichos_pausados}")
            
            if last_run:
                try:
                    if isinstance(last_run, str):
                        last_dt = datetime.fromisoformat(last_run)
                        last_str = last_dt.strftime('%d/%m %H:%M')
                    else:
                        last_str = str(last_run)
                    lines.append(f"  🕐 Última execução: {last_str}")
                except Exception:
                    lines.append(f"  🕐 Última execução: {last_run}")
            else:
                lines.append("  🕐 Última execução: Nunca")
        else:
            if hasattr(pipeline, 'sprint11_tracker') and pipeline.sprint11_tracker:
                ciclos = getattr(pipeline.sprint11_tracker, 'ciclos_realizados', 0) or 0
                lines.append(f"  🔄 Ciclos realizados: {_format_number(ciclos)}")
            else:
                lines.append("  🔄 Ciclos realizados: 0")
            lines.append("  ✅ Nichos ativos: N/A")
            lines.append("  ⏸️  Nichos pausados: N/A")
            lines.append("  🕐 Última execução: N/A")
    
    except Exception as e:
        logger.warning(f"Error building ViralX9 section: {e}")
        lines.append("  🚀 ViralX9: Erro ao acessar")
    
    lines.append("")
    return lines


async def _build_performance(pipeline: SeekerPipeline) -> List[str]:
    """Build Performance section."""
    lines = ["⚡ <b>PERFORMANCE</b>"]
    
    try:
        latency = 0.0
        success_rate = 0.0
        
        if hasattr(pipeline, 'analytics_dashboard') and pipeline.analytics_dashboard:
            latency = getattr(pipeline.analytics_dashboard, 'avg_latency', 0.0) or 0.0
            success_rate = getattr(pipeline.analytics_dashboard, 'success_rate', 0.0) or 0.0
        
        if latency > 0:
            lines.append(f"  ⏱️  Latência média: {latency:.2f}s")
        else:
            lines.append(f"  ⏱️  Latência média: N/A")
        
        lines.append(f"  📊 Taxa de sucesso: {success_rate*100:.1f}% {_progress_bar(success_rate)}")
        
        if hasattr(pipeline, 'reward_collector') and pipeline.reward_collector:
            try:
                rewards = getattr(pipeline.reward_collector, 'total_rewards', 0) or 0
                lines.append(f"  🎁 Rewards coletados: {_format_number(rewards)}")
            except Exception:
                pass

        if hasattr(pipeline, 'analytics_dashboard') and pipeline.analytics_dashboard:
            try:
                phase_stats = getattr(pipeline.analytics_dashboard, 'phase_stats', {}) or {}
                if phase_stats:
                    lines.append("  📈 Por fase:")
                    for phase, stats in list(phase_stats.items())[:3]:
                        if isinstance(stats, dict):
                            phase_success = stats.get('success_rate', stats.get('taxa_sucesso', 0))
                            phase_latency = stats.get('avg_latency', stats.get('latencia_media', 0))
                            lines.append(f"    • {phase}: {phase_success*100:.0f}% | {phase_latency:.2f}s")
            except Exception:
                pass
    
    except Exception as e:
        logger.warning(f"Error building Performance section: {e}")
        lines.append("  ⚡ Performance: Erro ao acessar")
    
    lines.append("")
    return lines


def setup_dashboard_handlers(dp: Dispatcher, pipeline: SeekerPipeline) -> None:
    """Register dashboard handlers with the dispatcher."""
    global _pipeline
    _pipeline = pipeline
    dp.include_router(router)
    logger.info("Dashboard handlers registered successfully")