from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputRichMessage, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repositories as repo
from bot.db.models import FavoriteQuery
from bot.handlers.queries import _run_sql_and_reply
from bot.keyboards.common import MENU_TEXT_FAVORITES
from bot.services.crypto import PasswordCipher
from bot.services.result_cache import ResultCache
from bot.services.table_format import (
    build_favorite_card_rich_message,
    build_favorite_connection_choice_rich_message,
    build_favorite_delete_confirm_rich_message,
    build_favorites_list_rich_message,
)

router = Router(name="favorites")
logger = logging.getLogger(__name__)


def _id_scope(data: str) -> tuple[int, str]:
    parts = data.split(":")
    item_id = int(parts[2])
    scope = parts[3] if len(parts) > 3 and parts[3] in {"all", "active"} else "all"
    return item_id, scope


async def _send_rich(
    message: Message,
    rich: InputRichMessage,
    *,
    edit: bool = False,
) -> None:
    if edit:
        try:
            await message.edit_text(rich_message=rich)
            return
        except TelegramBadRequest:
            pass
    await message.answer_rich(rich_message=rich)


async def _show_favorites_list(
    message: Message,
    session: AsyncSession,
    user_id: int,
    *,
    scope: str,
    edit: bool = False,
    notice: str | None = None,
) -> bool:
    connection_name: str | None = None
    if scope == "active":
        conn = await repo.get_active_connection(session, user_id)
        if conn is None:
            return False
        connection_name = conn.name
        favorites = await repo.list_favorites_for_connection(
            session, user_id, conn.id
        )
    else:
        favorites = await repo.list_all_favorites(session, user_id)
    rich = build_favorites_list_rich_message(
        favorites,
        scope=scope,
        connection_name=connection_name,
        notice=notice,
    )
    await _send_rich(message, rich, edit=edit)
    return True


async def _show_favorite_card(
    message: Message,
    fav: FavoriteQuery,
    *,
    scope: str,
    execute_on_name: str | None = None,
    edit: bool = True,
) -> None:
    rich = build_favorite_card_rich_message(
        fav,
        scope=scope,
        execute_on_name=execute_on_name,
    )
    await _send_rich(message, rich, edit=edit)


@router.message(Command("favorites"))
@router.message(F.text == MENU_TEXT_FAVORITES)
async def favorites_entry(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await _show_favorites_list(
        message,
        session,
        message.from_user.id,
        scope="all",
    )


@router.callback_query(F.data.in_({"fav:menu", "menu:favorites", "fav:list:all"}))
async def favorites_list_all(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await _show_favorites_list(
        callback.message,
        session,
        callback.from_user.id,
        scope="all",
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data == "fav:list:active")
async def favorites_list_active(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    shown = await _show_favorites_list(
        callback.message,
        session,
        callback.from_user.id,
        scope="active",
        edit=True,
    )
    if not shown:
        await callback.answer("Сначала выберите подключение.", show_alert=True)
        return
    await callback.answer()


@router.callback_query(F.data.startswith("fav:view:"))
async def view_favorite(callback: CallbackQuery, session: AsyncSession) -> None:
    favorite_id, scope = _id_scope(callback.data)
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return

    active = await repo.get_active_connection(session, callback.from_user.id)
    if active is not None and active.id != fav.connection_id:
        rich = build_favorite_connection_choice_rich_message(
            fav,
            active_name=active.name,
            scope=scope,
        )
        await _send_rich(callback.message, rich, edit=True)
        await callback.answer()
        return

    await _show_favorite_card(callback.message, fav, scope=scope)
    await callback.answer()


@router.callback_query(F.data.startswith("fav:switch:"))
async def switch_to_favorite_connection(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    favorite_id, scope = _id_scope(callback.data)
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.set_active_connection(session, callback.from_user.id, fav.connection_id)
    logger.info(
        "user=%s switch_from_favorite id=%s connection_id=%s",
        callback.from_user.id,
        fav.id,
        fav.connection_id,
    )
    await _show_favorite_card(callback.message, fav, scope=scope)
    await callback.answer("Подключение выбрано")


@router.callback_query(F.data.startswith("fav:keep:"))
async def keep_current_connection(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    favorite_id, scope = _id_scope(callback.data)
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    active = await repo.get_active_connection(session, callback.from_user.id)
    execute_on_name = active.name if active is not None else None
    await _show_favorite_card(
        callback.message,
        fav,
        scope=scope,
        execute_on_name=execute_on_name,
    )
    await callback.answer("Оставляю текущее")


@router.callback_query(F.data.startswith("fav:run:") | F.data.startswith("fav:edit:"))
async def run_favorite(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
    result_cache: ResultCache,
) -> None:
    favorite_id = int(callback.data.split(":")[2])
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return

    active = await repo.get_active_connection(session, callback.from_user.id)
    if active is None:
        await repo.set_active_connection(
            session, callback.from_user.id, fav.connection_id
        )
        run_connection_id = fav.connection_id
    else:
        run_connection_id = active.id
    logger.info(
        "user=%s run_favorite id=%s connection_id=%s",
        callback.from_user.id,
        fav.id,
        run_connection_id,
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


@router.callback_query(F.data.regexp(r"^fav:delete:\d+:(all|active)$"))
async def delete_favorite_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    favorite_id, scope = _id_scope(callback.data)
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    rich = build_favorite_delete_confirm_rich_message(fav, scope=scope)
    await _send_rich(callback.message, rich, edit=True)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^fav:delete_confirm:\d+:(all|active)$"))
async def delete_favorite_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    favorite_id, scope = _id_scope(callback.data)
    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    title = fav.title
    await repo.delete_favorite(session, fav)
    logger.info("user=%s delete_favorite id=%s", callback.from_user.id, favorite_id)
    shown = await _show_favorites_list(
        callback.message,
        session,
        callback.from_user.id,
        scope=scope,
        edit=True,
        notice=f"Избранное «{title}» удалено.",
    )
    if not shown:
        await _show_favorites_list(
            callback.message,
            session,
            callback.from_user.id,
            scope="all",
            edit=True,
            notice=f"Избранное «{title}» удалено.",
        )
    await callback.answer()
