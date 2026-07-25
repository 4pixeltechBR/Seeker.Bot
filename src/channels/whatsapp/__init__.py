"""WhatsApp channel exports."""

from .client import WhatsAppClient
from .router import HANDLERS, dispatch_message, summarize_batch
from .webhook import process_webhook_payload

__all__ = ["WhatsAppClient", "HANDLERS", "dispatch_message", "summarize_batch", "process_webhook_payload"]
