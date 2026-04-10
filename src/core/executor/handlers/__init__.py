"""
Action handlers for Remote Executor.

Pluggable handlers for different action types:
- BashHandler: Execute bash commands (subprocess)
- FileOpsHandler: Safe file operations (read, write, delete)
- APIHandler: HTTP requests (GET, POST, PATCH, DELETE)
- RemoteTriggerHandler: Delegate to Claude Code (desktop actions)

Usage:
    handler = get_handler("bash")
    result = await handler.execute(step)
"""

from .bash import BashHandler
from .file_ops import FileOpsHandler
from .api import APIHandler
from .remote_trigger import RemoteTriggerHandler

__all__ = [
    "BashHandler",
    "FileOpsHandler",
    "APIHandler",
    "RemoteTriggerHandler",
    "get_handler",
]

# Global handler instances (created on first use)
_handlers = {}


def get_handler(handler_type: str):
    """
    Get handler by type (singleton pattern).

    Args:
        handler_type: "bash", "file_ops", "api", "remote_trigger"

    Returns:
        Handler instance

    Raises:
        ValueError: Unknown handler type
    """
    valid_types = ["bash", "file_ops", "api", "remote_trigger"]

    if handler_type not in valid_types:
        raise ValueError(f"Unknown handler type: {handler_type}")

    # Lazy init
    if handler_type not in _handlers:
        if handler_type == "bash":
            _handlers[handler_type] = BashHandler()
        elif handler_type == "file_ops":
            _handlers[handler_type] = FileOpsHandler()
        elif handler_type == "api":
            _handlers[handler_type] = APIHandler()
        elif handler_type == "remote_trigger":
            _handlers[handler_type] = RemoteTriggerHandler()

    return _handlers[handler_type]
