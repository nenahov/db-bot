from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from aiogram import Bot
from aiogram.enums import ChatMemberStatus
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, ChatMember, Message

from bot.config import Settings
from bot.keyboards.common import subscribe_gate_kb

logger = logging.getLogger(__name__)

AUTH_CHECK_CALLBACK = "auth:check"
GATE_TEXT = "Чтобы пользоваться ботом, вступите в сообщество."
_SUBSCRIBE_INFO_TTL_SEC = 3600

_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
}


@dataclass(frozen=True)
class SubscribeTarget:
    chat_id: int
    title: str
    url: str | None


class MembershipCache:
    def __init__(self, ttl_sec: int) -> None:
        self.ttl_sec = ttl_sec
        self._ok_until: dict[int, float] = {}
        self._chats: dict[int, tuple[float, SubscribeTarget]] = {}

    def is_allowed(self, user_id: int) -> bool:
        self._cleanup()
        expires = self._ok_until.get(user_id)
        return expires is not None and expires > time.time()

    def remember(self, user_id: int) -> None:
        self._ok_until[user_id] = time.time() + self.ttl_sec

    def get_subscribe_target(self, chat_id: int) -> SubscribeTarget | None:
        self._cleanup()
        cached = self._chats.get(chat_id)
        if cached is None:
            return None
        return cached[1]

    def store_subscribe_target(self, target: SubscribeTarget) -> None:
        self._chats[target.chat_id] = (time.time() + _SUBSCRIBE_INFO_TTL_SEC, target)

    def _cleanup(self) -> None:
        now = time.time()
        expired_users = [
            user_id for user_id, expires in self._ok_until.items() if expires <= now
        ]
        for user_id in expired_users:
            del self._ok_until[user_id]
        expired_chats = [
            chat_id for chat_id, (expires, _) in self._chats.items() if expires <= now
        ]
        for chat_id in expired_chats:
            del self._chats[chat_id]


def is_active_member(member: ChatMember) -> bool:
    if member.status in _MEMBER_STATUSES:
        return True
    if member.status == ChatMemberStatus.RESTRICTED:
        return bool(getattr(member, "is_member", False))
    return False


async def user_is_member(bot: Bot, user_id: int, group_ids: list[int]) -> bool:
    for chat_id in group_ids:
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except TelegramAPIError as exc:
            logger.warning(
                "membership check failed chat=%s user=%s: %s",
                chat_id,
                user_id,
                exc,
            )
            continue
        if is_active_member(member):
            return True
    return False


async def resolve_subscribe_targets(
    bot: Bot,
    cache: MembershipCache,
    group_ids: list[int],
    limit: int,
) -> list[SubscribeTarget]:
    targets: list[SubscribeTarget] = []
    for chat_id in group_ids[: max(limit, 0)]:
        targets.append(await _resolve_subscribe_target(bot, cache, chat_id))
    return targets


def subscribe_buttons(targets: list[SubscribeTarget]) -> list[tuple[str, str]]:
    with_url = [(target.title, target.url) for target in targets if target.url]
    multi = len(with_url) > 1
    return [
        (f"Подписаться: {title}" if multi else "Подписаться", url)
        for title, url in with_url
    ]


async def send_access_gate(
    event: Message | CallbackQuery,
    bot: Bot,
    settings: Settings,
    cache: MembershipCache,
    *,
    callback_text: str | None = None,
) -> None:
    targets = await resolve_subscribe_targets(
        bot,
        cache,
        settings.auth_group_ids,
        settings.auth_subscribe_count,
    )
    markup = subscribe_gate_kb(subscribe_buttons(targets))
    if isinstance(event, CallbackQuery):
        message = event.message
        if isinstance(message, Message):
            try:
                await message.edit_text(GATE_TEXT, reply_markup=markup)
            except TelegramBadRequest:
                pass
        await event.answer(callback_text or "")
        return
    await event.answer(GATE_TEXT, reply_markup=markup)


async def _resolve_subscribe_target(
    bot: Bot,
    cache: MembershipCache,
    chat_id: int,
) -> SubscribeTarget:
    cached = cache.get_subscribe_target(chat_id)
    if cached is not None:
        return cached

    target = await _fetch_subscribe_target(bot, chat_id)
    cache.store_subscribe_target(target)
    return target


async def _fetch_subscribe_target(bot: Bot, chat_id: int) -> SubscribeTarget:
    try:
        chat = await bot.get_chat(chat_id)
    except TelegramAPIError as exc:
        logger.warning("cannot resolve chat %s: %s", chat_id, exc)
        return SubscribeTarget(chat_id=chat_id, title=str(chat_id), url=None)

    title = chat.title or (f"@{chat.username}" if chat.username else str(chat_id))
    url: str | None = None
    if chat.username:
        url = f"https://t.me/{chat.username}"
    elif chat.invite_link:
        url = chat.invite_link
    else:
        try:
            url = await bot.export_chat_invite_link(chat_id)
        except TelegramAPIError as extra:
            logger.warning("no invite link for chat %s: %s", chat_id, extra)
    return SubscribeTarget(chat_id=chat_id, title=title, url=url)
