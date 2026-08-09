import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

action_logger = logging.getLogger("bot.actions")


class ActionLogMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        user_id = user.id if user else "-"

        if isinstance(event, Message) and event.text:
            text = event.text.replace("\n", " ")
            if len(text) > 200:
                text = text[:200] + "…"
            action_logger.info("user=%s message=%s", user_id, text)
        elif isinstance(event, CallbackQuery):
            action_logger.info("user=%s callback=%s", user_id, event.data)

        return await handler(event, data)
