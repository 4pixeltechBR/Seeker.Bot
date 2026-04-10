"""
Remote Executor — Sistema Autônomo de Execução para Seeker.Bot

Módulo principal para orquestração de ações multi-step, com suporte a:
- Planejamento LLM (ActionOrchestrator)
- Execução sequencial com rollback (ActionExecutor)
- Safety gates e approval workflows (SafetyGate, AFKProtocol)
- Handlers plugáveis (bash, file_ops, api, remote_trigger)

Exports:
    - ExecutionPlan, ActionStep, ExecutionResult: dataclasses
    - ActionHandler: protocolo para handlers
    - ActionOrchestrator: LLM planning
    - ActionExecutor: sequential execution
    - SafetyGateEvaluator: permission gates
    - AFKProtocolCoordinator: user status tracking
"""

__version__ = "1.0.0"
__all__ = [
    # Models
    "ExecutionPlan",
    "ActionStep",
    "ExecutionResult",
    "ActionType",
    "AutonomyTier",
    # Base
    "ActionHandler",
    # Will be added: Orchestrator, Executor, Safety, AFK
]
