"""
Remote Executor — Goal Autônomo para Execução de Ações Multi-step

Responsabilidades:
- Escuta intenções de usuário com tipo ACTION + autonomy tier
- Usa ActionOrchestrator para planejar steps
- Usa ActionExecutor para executar sequencialmente
- Gerencia AFK Protocol (approval queues, escalation)
- Integra com Safety Gates (whitelist, budget enforcement)
- Notifica via Telegram com audit trail

Implementa AutonomousGoal protocol.
"""

from .goal import RemoteExecutorGoal
from .config import REMOTE_EXECUTOR_CONFIG

__all__ = ["RemoteExecutorGoal", "REMOTE_EXECUTOR_CONFIG"]
