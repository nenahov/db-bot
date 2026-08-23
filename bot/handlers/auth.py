import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import ChatMemberUpdatedFilter, Command
from aiogram.filters.chat_member_updated import IS_MEMBER, IS_NOT_MEMBER
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.config import Settings
from bot.handlers.start import MAIN_MENU_TEXT
from bot.keyboards.common import main_menu_kb
from bot.services.membership import (
    AUTH_CHECK_CALLBACK,
    MembershipCache,
    send_access_gate,
    user_is_member,
)

logger = logging.getLogger(__name__)

router = Router()


def _chat_id_text(chat_id: int) -> str:
    return f"Идентификатор чата: <code>{chat_id}</code>"


@router.my_chat_member(ChatMemberUpdatedFilter(IS_NOT_MEMBER >> IS_MEMBER))
async def bot_added_to_chat(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        await bot.send_message(
            event.chat.id,
            "Бот добавлен в этот чат.\n" + _chat_id_text(event.chat.id),
        )
    except TelegramAPIError as exc:
        logger.warning("cannot send chat id to %s: %s", event.chat.id, exc)


@router.message(Command("chatid"))
async def cmd_chatid(message: Message) -> None:
    await message.answer(_chat_id_text(message.chat.id))


@router.callback_query(F.data == AUTH_CHECK_CALLBACK)
async def check_subscription(
    callback: CallbackQuery,
    bot: Bot,
    settings: Settings,
    membership_cache: MembershipCache,
) -> None:
    if not settings.auth_group_ids:
        await callback.answer()
        return

    if await user_is_member(bot, callback.from_user.id, settings.auth_group_ids):
        membership_cache.remember(callback.from_user.id)
        if isinstance(callback.message, Message):
            try:
                await callback.message.edit_text(
                    MAIN_MENU_TEXT,
                    reply_markup=main_menu_kb(),
                )
            except TelegramBadRequest:
                await callback.message.answer(
                    MAIN_MENU_TEXT,
                    reply_markup=main_menu_kb(),
                )
        await callback.answer("Доступ разрешён")
        return

    await send_access_gate(
        callback,
        bot,
        settings,
        membership_cache,
        callback_text="Подписка не найдена",
    )
