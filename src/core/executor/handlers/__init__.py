"""Action Handlers for Remote Executor — Track B2"""

from .bash import BashHandler
from .file_ops import FileOpsHandler
from .api import APIHandler
from .remote_trigger import RemoteTriggerHandler


def get_handler(action_type: str):
    """Factory function para obter handler baseado no tipo de ação"""
    handlers = {
        "bash": BashHandler(),
        "file_ops": FileOpsHandler(),
        "api": APIHandler(),
        "remote_trigger": RemoteTriggerHandler(),
    }
    return handlers.get(action_type)


__all__ = [
    "BashHandler",
    "FileOpsHandler",
    "APIHandler",
    "RemoteTriggerHandler",
    "get_handler",
]
