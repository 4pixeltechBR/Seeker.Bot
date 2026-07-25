from typing import Callable, Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
import logging

log = logging.getLogger("seeker.telegram.auth")


class AuthMiddleware(BaseMiddleware):
    """Blocks any user not in `allowed_users`.

    If `allowed_users` is empty the bot is considered open and everyone passes.
    """

    def __init__(self, allowed_users: set[int]):
        super().__init__()
        self.allowed_users = allowed_users

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Any],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Open-access mode — no restriction configured
        if not self.allowed_users:
            return await handler(event, data)

        user_id = None
        username = "?"
        text_preview = "?"
        if hasattr(event, "from_user") and event.from_user:
            user_id = event.from_user.id
            username = event.from_user.username or event.from_user.full_name or str(user_id)
        if hasattr(event, "text") and event.text:
            text_preview = event.text[:80]
        elif hasattr(event, "data") and event.data:
            text_preview = f"callback:{event.data[:80]}"

        if user_id and user_id in self.allowed_users:
            log.info(f"[auth] Permitido — user={username} id={user_id} | msg='{text_preview}'")
            return await handler(event, data)

        log.warning(f"[auth] Acesso NEGADO — user_id={user_id} username={username} | msg='{text_preview}'")
        return  # Drop the update silently