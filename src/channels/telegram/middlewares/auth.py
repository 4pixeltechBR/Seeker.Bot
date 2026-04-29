from typing import Callable, Any

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
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

        user_id: int | None = getattr(event, "from_user", None) and event.from_user.id

        if user_id and user_id in self.allowed_users:
            return await handler(event, data)

        log.warning(f"[auth] Acesso negado — user_id={user_id}")
        return  # Drop the update silently
