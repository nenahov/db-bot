from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repositories as repo
from bot.keyboards.common import (
    MENU_TEXT_FAVORITES,
    favorite_card_kb,
    favorites_list_kb,
    favorites_menu_kb,
    main_menu_kb,
)
from bot.states.forms import QueryForm

router = Router(name="favorites")
logger = logging.getLogger(__name__)


async def send_favorites_menu(target: Message) -> None:
    await target.answer(
        "Избранные запросы:",
        reply_markup=favorites_menu_kb(),
    )


@router.message(F.text == MENU_TEXT_FAVORITES)
async def favorites_entry(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_favorites_menu(message)


@router.callback_query(F.data == "fav:menu")
async def favorites_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Избранные запросы:",
        reply_markup=favorites_menu_kb(),
    )
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


@router.callback_query(F.data.startswith("fav:edit:"))
async def edit_and_run_favorite(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    favorite_id = int(callback.data.split(":")[-1])
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return

    await repo.set_active_connection(session, callback.from_user.id, fav.connection_id)
    await state.set_state(QueryForm.editing_sql)
    await state.update_data(last_sql=fav.sql_text)
    logger.info(
        "user=%s edit_favorite id=%s connection_id=%s",
        callback.from_user.id,
        fav.id,
        fav.connection_id,
    )
    conn_label = fav.connection.name if fav.connection else str(fav.connection_id)
    await callback.message.answer(
        "Подключение переключено на "
        f"<b>{html.escape(conn_label)}</b>.\n"
        "Отредактируйте SQL и отправьте сообщение для выполнения:\n\n"
        f"<pre>{html.escape(fav.sql_text)}</pre>",
        reply_markup=main_menu_kb(),
    )
    await callback.answer()


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
