from __future__ import annotations

import html
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InputRichMessage, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repositories as repo
from bot.db.models import DbConnection
from bot.keyboards.common import (
    MENU_TEXT_QUERY,
    MENU_TEXTS,
    cancel_kb,
    confirm_replace_favorite_kb,
    main_menu_kb,
    query_result_kb,
)
from bot.services.crypto import PasswordCipher
from bot.services.executors import QueryResult, execute_sql
from bot.services.result_cache import ResultCache
from bot.services.table_format import build_result_rich_message
from bot.states.forms import FavoriteForm, QueryForm

router = Router(name="queries")
logger = logging.getLogger(__name__)


def _store_table_result(
    user_id: int,
    *,
    sql: str,
    conn: DbConnection,
    result: QueryResult,
    settings: Settings,
    result_cache: ResultCache,
) -> tuple[str, InputRichMessage]:
    run_id = result_cache.put(
        user_id,
        result.columns,
        result.rows,
        sql=sql,
        connection_id=conn.id,
    )
    total_rows = result.rowcount if result.rowcount is not None else len(result.rows)
    rich = build_result_rich_message(
        result.columns,
        result.rows,
        connection_name=conn.name,
        preview_rows=settings.query_preview_rows,
        total_rows=total_rows,
        elapsed_ms=result.elapsed_ms,
        run_id=run_id,
    )
    return run_id, rich


async def _run_sql_and_reply(
    message: Message,
    *,
    user_id: int,
    sql: str,
    session: AsyncSession,
    state: FSMContext,
    cipher: PasswordCipher,
    settings: Settings,
    result_cache: ResultCache,
) -> None:
    conn = await repo.get_active_connection(session, user_id)
    if conn is None:
        await state.clear()
        await message.answer(
            "Активное подключение не выбрано.",
            reply_markup=main_menu_kb(),
        )
        return

    await state.update_data(last_sql=sql)
    status = await message.answer("Выполняю запрос…")
    logger.info(
        "user=%s run_query connection_id=%s sql=%s",
        user_id,
        conn.id,
        sql[:300].replace("\n", " "),
    )

    try:
        result = await execute_sql(
            conn,
            cipher,
            sql,
            timeout_sec=settings.query_timeout_sec,
            max_rows=settings.query_max_rows,
        )
    except Exception as exc:
        logger.warning("user=%s query_failed: %s", user_id, exc)
        await status.edit_text(
            f"Ошибка выполнения:\n<code>{html.escape(str(exc))}</code>"
        )
        await state.set_state(QueryForm.waiting_sql)
        return

    if not result.has_dataset:
        await state.set_state(QueryForm.waiting_sql)
        affected = "n/a" if result.rowcount is None else str(result.rowcount)
        await status.edit_text(
            f"Готово за {result.elapsed_ms} мс.\n"
            f"Затронуто строк: {affected}",
            reply_markup=query_result_kb(None, can_favorite=True),
        )
        return

    run_id, rich = _store_table_result(
        user_id,
        sql=sql,
        conn=conn,
        result=result,
        settings=settings,
        result_cache=result_cache,
    )
    await status.delete()
    await message.answer_rich(
        rich_message=rich,
        reply_markup=query_result_kb(run_id, can_favorite=True),
    )
    await state.set_state(QueryForm.waiting_sql)


@router.message(F.text == MENU_TEXT_QUERY)
async def legacy_query_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Просто отправьте SQL-запрос одним сообщением.")


@router.message(
    StateFilter(None, QueryForm.waiting_sql),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(MENU_TEXTS),
)
async def receive_sql(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
    result_cache: ResultCache,
) -> None:
    sql = (message.text or "").strip()
    if not sql:
        await message.answer("Пустой запрос. Отправьте SQL текстом.")
        return
    await _run_sql_and_reply(
        message,
        user_id=message.from_user.id,
        sql=sql,
        session=session,
        state=state,
        cipher=cipher,
        settings=settings,
        result_cache=result_cache,
    )


@router.callback_query(F.data.startswith("query:csv:"))
async def download_csv(
    callback: CallbackQuery,
    result_cache: ResultCache,
) -> None:
    run_id = callback.data.split(":")[-1]
    item = result_cache.get(run_id, callback.from_user.id)
    if item is None:
        await callback.answer("Результат устарел. Выполните запрос снова.", show_alert=True)
        return
    payload = result_cache.to_csv_bytes(item)
    document = BufferedInputFile(payload, filename=f"result_{run_id[:8]}.csv")
    await callback.message.answer_document(document)
    logger.info("user=%s download_csv run_id=%s", callback.from_user.id, run_id)
    await callback.answer()


@router.callback_query(F.data.startswith("query:refresh:"))
async def refresh_query(
    callback: CallbackQuery,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
    result_cache: ResultCache,
) -> None:
    run_id = callback.data.split(":")[-1]
    item = result_cache.get(run_id, callback.from_user.id)
    if item is None:
        await callback.answer("Результат устарел. Выполните запрос снова.", show_alert=True)
        return

    conn = await repo.get_connection(
        session, callback.from_user.id, item.connection_id
    )
    if conn is None:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    logger.info(
        "user=%s refresh_query connection_id=%s sql=%s",
        callback.from_user.id,
        conn.id,
        item.sql[:300].replace("\n", " "),
    )
    try:
        result = await execute_sql(
            conn,
            cipher,
            item.sql,
            timeout_sec=settings.query_timeout_sec,
            max_rows=settings.query_max_rows,
        )
    except Exception as exc:
        logger.warning("user=%s refresh_failed: %s", callback.from_user.id, exc)
        await callback.answer(
            f"Ошибка выполнения: {exc}"[:200],
            show_alert=True,
        )
        return

    if not result.has_dataset:
        await callback.answer("Запрос не вернул таблицу.", show_alert=True)
        return

    new_run_id, rich = _store_table_result(
        callback.from_user.id,
        sql=item.sql,
        conn=conn,
        result=result,
        settings=settings,
        result_cache=result_cache,
    )
    try:
        await callback.message.edit_text(
            rich_message=rich,
            reply_markup=query_result_kb(new_run_id, can_favorite=True),
        )
    except TelegramBadRequest:
        pass
    await callback.answer(f"Обновлено за {result.elapsed_ms} мс")


async def _prompt_replace_favorite(
    message: Message,
    state: FSMContext,
    *,
    title: str,
    favorite_id: int,
) -> None:
    await state.update_data(replace_favorite_id=favorite_id)
    await state.set_state(FavoriteForm.confirming_replace)
    await message.answer(
        f"В избранном уже есть запрос «{html.escape(title)}» "
        "для этого подключения. Заменить его новым SQL?",
        reply_markup=confirm_replace_favorite_kb(),
    )


async def _finish_favorite_saved(
    message: Message,
    state: FSMContext,
    title: str,
    *,
    user_id: int,
) -> None:
    await state.set_state(QueryForm.waiting_sql)
    logger.info("user=%s add_favorite title=%s", user_id, title)
    await message.answer(
        f"Сохранено в избранное: «{html.escape(title)}».\n"
        "Можете отправить следующий SQL.",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "query:fav")
async def save_favorite_start(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    sql = data.get("last_sql")
    if not sql:
        await callback.answer("Нет последнего запроса для сохранения.", show_alert=True)
        return
    await state.set_state(FavoriteForm.waiting_title)
    await callback.message.answer(
        "Введите название для избранного запроса:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(FavoriteForm.waiting_title, F.text, ~F.text.in_(MENU_TEXTS))
async def save_favorite_title(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    title = (message.text or "").strip()
    if not title or len(title) > 128:
        await message.answer("Название обязательно, до 128 символов.")
        return

    data = await state.get_data()
    sql = data.get("last_sql")
    conn = await repo.get_active_connection(session, message.from_user.id)
    if not sql or conn is None:
        await state.clear()
        await message.answer(
            "Не удалось сохранить: нет активного подключения или SQL.",
            reply_markup=main_menu_kb(),
        )
        return

    existing = await repo.get_favorite_by_title(
        session,
        message.from_user.id,
        conn.id,
        title,
    )
    if existing is not None:
        await _prompt_replace_favorite(
            message,
            state,
            title=title,
            favorite_id=existing.id,
        )
        return

    try:
        fav = await repo.create_favorite(
            session,
            user_id=message.from_user.id,
            connection_id=conn.id,
            title=title,
            sql_text=sql,
        )
    except Exception as exc:
        await message.answer(f"Не удалось сохранить: {exc}")
        return

    await _finish_favorite_saved(
        message,
        state,
        fav.title,
        user_id=message.from_user.id,
    )


@router.callback_query(
    FavoriteForm.confirming_replace,
    F.data == "query:fav:replace",
)
async def replace_favorite_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    data = await state.get_data()
    sql = data.get("last_sql")
    favorite_id = data.get("replace_favorite_id")
    if not sql or favorite_id is None:
        await state.clear()
        await callback.answer("Не удалось заменить запрос.", show_alert=True)
        return

    fav = await repo.get_favorite(session, callback.from_user.id, favorite_id)
    if fav is None:
        await state.set_state(QueryForm.waiting_sql)
        await callback.answer("Избранное не найдено.", show_alert=True)
        return

    await repo.update_favorite_sql(session, fav, sql)
    logger.info(
        "user=%s replace_favorite id=%s",
        callback.from_user.id,
        fav.id,
    )
    await state.set_state(QueryForm.waiting_sql)
    text = (
        f"Запрос «{html.escape(fav.title)}» в избранном заменён.\n"
        "Можете отправить следующий SQL."
    )
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=main_menu_kb())
    await callback.answer()


@router.message(FavoriteForm.confirming_replace, ~F.text.in_(MENU_TEXTS))
async def replace_favorite_need_confirm(message: Message) -> None:
    await message.answer(
        "Подтвердите замену кнопками ниже или нажмите «Отмена».",
        reply_markup=confirm_replace_favorite_kb(),
    )
