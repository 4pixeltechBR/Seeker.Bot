"""
Remote Executor Configuration

Constantes, defaults e configurações para o RemoteExecutor goal.
"""

from enum import Enum


class RemoteExecutorConfig:
    """Configuração centralizada do Remote Executor."""

    # Scheduling
    INTERVAL_SECONDS = 60  # Polling interval para checks de approval queue, etc
    APPROVAL_TIMEOUT_SECONDS = 300  # 5 min para user responder aprovação
    APPROVAL_MAX_RETRIES = 3  # Quantas vezes re-enviar notificação antes de timeout

    # Budget
    MAX_COST_PER_CYCLE_USD = 0.20  # Hardcap por ciclo
    MAX_COST_PER_DAY_USD = 1.00  # Budget diário
    ORCHESTRATOR_COST_ESTIMATE_USD = 0.05  # Custo de chamar LLM planning

    # AFK Window
    AFK_WINDOW_L1_LOGGED_HOURS = 12  # L1 pode executar até 12h AFK
    AFK_WINDOW_ESCALATE_HOURS = 6  # Escalate Telegram se > 6h AFK
    AFK_WINDOW_L0_MANUAL_MINUTES = 5  # L0 aguarda 5 min de aprovação

    # Orchestrator
    MAX_ORCHESTRATION_STEPS = 10
    MAX_TOTAL_TIMEOUT_SECONDS = 60
    MAX_PLAN_COST_USD = 0.20

    # Notification templates
    TELEGRAM_APPROVAL_TEMPLATE = (
        "🔑 Aprovação necessária:\n\n"
        "{description}\n\n"
        "Timeout: {timeout_seconds}s\n"
        "Custo estimado: ${cost_usd:.2f}\n\n"
        "[Aprove] [Rejeite]"
    )

    TELEGRAM_EXECUTION_TEMPLATE = (
        "✅ Execução completa:\n\n"
        "{summary}\n\n"
        "Steps: {step_count}\n"
        "Sucesso: {success_count}\n"
        "Custo total: ${total_cost_usd:.2f}\n"
        "Duração: {duration_ms}ms"
    )

    TELEGRAM_FAILURE_TEMPLATE = (
        "❌ Execução falhou:\n\n"
        "{error}\n\n"
        "Plano: {plan_id}"
    )


# Singleton exportado
REMOTE_EXECUTOR_CONFIG = RemoteExecutorConfig()
