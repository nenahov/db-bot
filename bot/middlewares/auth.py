from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    Message,
    TelegramObject,
    Update,
)

from bot.config import Settings
from bot.services.membership import (
    AUTH_CHECK_CALLBACK,
    MembershipCache,
    send_access_gate,
    user_is_member,
)


class AuthMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings: Settings = data["settings"]
        if not settings.auth_group_ids:
            return await handler(event, data)

        inner = _unwrap(event)
        if isinstance(inner, ChatMemberUpdated):
            return await handler(event, data)

        if _is_auth_check(inner):
            return await handler(event, data)

        if not _is_private(inner):
            return await handler(event, data)

        user = data.get("event_from_user") or getattr(inner, "from_user", None)
        if user is None:
            return await handler(event, data)

        cache: MembershipCache = data["membership_cache"]
        if cache.is_allowed(user.id):
            return await handler(event, data)

        bot: Bot = data["bot"]
        if await user_is_member(bot, user.id, settings.auth_group_ids):
            cache.remember(user.id)
            return await handler(event, data)

        if isinstance(inner, (Message, CallbackQuery)):
            await send_access_gate(
                inner,
                bot,
                settings,
                cache,
                callback_text="Нет доступа",
            )
        return None


def _unwrap(event: TelegramObject) -> TelegramObject:
    if not isinstance(event, Update):
        return event
    return (
        event.message
        or event.edited_message
        or event.callback_query
        or event.my_chat_member
        or event.chat_member
        or event.channel_post
        or event.edited_channel_post
        or event
    )


def _is_auth_check(event: TelegramObject) -> bool:
    return isinstance(event, CallbackQuery) and event.data == AUTH_CHECK_CALLBACK


def _is_private(event: TelegramObject) -> bool:
    if isinstance(event, Message):
        return event.chat.type == ChatType.PRIVATE
    if isinstance(event, CallbackQuery) and event.message is not None:
        return event.message.chat.type == ChatType.PRIVATE
    return False
