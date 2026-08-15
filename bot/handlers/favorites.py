from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repositories as repo
from bot.handlers.queries import _run_sql_and_reply
from bot.keyboards.common import (
    MENU_TEXT_FAVORITES,
    favorite_card_kb,
    favorites_list_kb,
    favorites_menu_kb,
)
from bot.services.crypto import PasswordCipher
from bot.services.result_cache import ResultCache

router = Router(name="favorites")
logger = logging.getLogger(__name__)


@router.message(F.text == MENU_TEXT_FAVORITES)
async def favorites_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Избранные запросы:",
        reply_markup=favorites_menu_kb(),
    )


@router.callback_query(F.data.in_({"fav:menu", "menu:favorites"}))
async def favorites_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    text = "Избранные запросы:"
    markup = favorites_menu_kb()
    try:
        await callback.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data == "fav:list:active")
async def list_favorites_active(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    conn = await repo.get_active_connection(session, callback.from_user.id)
    if conn is None:
        await callback.answer("Сначала выберите подключение.", show_alert=True)
        return
    favorites = await repo.list_favorites_for_connection(
        session,
        callback.from_user.id,
        conn.id,
    )
    if not favorites:
        await callback.message.edit_text(
            f"В «{conn.name}» избранных запросов нет.",
            reply_markup=favorites_menu_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Избранное для «{conn.name}»:",
        reply_markup=favorites_list_kb(favorites, show_connection_name=False),
    )
    await callback.answer()


@router.callback_query(F.data == "fav:list:all")
async def list_favorites_all(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    favorites = await repo.list_all_favorites(session, callback.from_user.id)
    if not favorites:
        await callback.message.edit_text(
            "Избранных запросов пока нет.",
            reply_markup=favorites_menu_kb(),
        )
        await callback.answer()
        return
    await callback.message.edit_text(
        "Все избранные:",
        reply_markup=favorites_list_kb(favorites, show_connection_name=True),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fav:view:"))
async def view_favorite(callback: CallbackQuery, session: AsyncSession) -> None:
    favorite_id = int(callback.data.split(":")[-1])
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    conn_name = fav.connection.name if fav.connection else "?"
    await callback.message.edit_text(
        f"<b>{html.escape(fav.title)}</b>\n"
        f"Подключение: <code>{html.escape(conn_name)}</code>\n\n"
        f"<pre>{html.escape(fav.sql_text)}</pre>",
        reply_markup=favorite_card_kb(fav.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("fav:run:") | F.data.startswith("fav:edit:"))
async def run_favorite(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
    result_cache: ResultCache,
) -> None:
    favorite_id = int(callback.data.split(":")[-1])
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return

    await repo.set_active_connection(session, callback.from_user.id, fav.connection_id)
    logger.info(
        "user=%s run_favorite id=%s connection_id=%s",
        callback.from_user.id,
        fav.id,
        fav.connection_id,
    )
    await callback.answer("Выполняю…")
    await _run_sql_and_reply(
        callback.message,
        user_id=callback.from_user.id,
        sql=fav.sql_text,
        session=session,
        state=state,
        cipher=cipher,
        settings=settings,
        result_cache=result_cache,
    )


@router.callback_query(F.data.startswith("fav:delete:"))
async def delete_favorite(callback: CallbackQuery, session: AsyncSession) -> None:
    favorite_id = int(callback.data.split(":")[-1])
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    title = fav.title
    await repo.delete_favorite(session, fav)
    logger.info("user=%s delete_favorite id=%s", callback.from_user.id, favorite_id)
    await callback.message.edit_text(
        f"Избранное «{title}» удалено.",
        reply_markup=favorites_menu_kb(),
    )
    await callback.answer()
