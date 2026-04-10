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

__all__ = [
    "BashHandler",
    "FileOpsHandler",
    "APIHandler",
    "RemoteTriggerHandler",
    "get_handler",
]

# Will be imported when modules are ready
# from .bash import BashHandler
# from .file_ops import FileOpsHandler
# from .api import APIHandler
# from .remote_trigger import RemoteTriggerHandler


def get_handler(handler_type: str):
    """
    Get handler by type.

    Args:
        handler_type: "bash", "file_ops", "api", "remote_trigger"

    Returns:
        Handler instance

    Raises:
        ValueError: Unknown handler type
    """
    handlers = {
        "bash": None,  # Will be: BashHandler()
        "file_ops": None,  # Will be: FileOpsHandler()
        "api": None,  # Will be: APIHandler()
        "remote_trigger": None,  # Will be: RemoteTriggerHandler()
    }

    if handler_type not in handlers:
        raise ValueError(f"Unknown handler type: {handler_type}")

    handler = handlers.get(handler_type)
    if handler is None:
        raise RuntimeError(f"Handler {handler_type} not yet initialized")

    return handler
