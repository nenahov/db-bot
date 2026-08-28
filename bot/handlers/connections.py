from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import Settings
from bot.db import repositories as repo
from bot.db.models import DbConnection, DbType
from bot.keyboards.common import (
    MENU_TEXT_CONNECTIONS,
    MENU_TEXTS,
    cancel_kb,
    confirm_delete_kb,
    connection_edit_fields_kb,
    connections_list_kb,
    db_type_kb,
    main_menu_kb,
    read_only_choice_kb,
    read_only_edit_kb,
    skip_default_port_kb,
)
from bot.services.connection_card import (
    ConnectionCardParseError,
    looks_like_connection_card,
    parse_connection_card,
)
from bot.services.crypto import PasswordCipher
from bot.services.executors import test_connection
from bot.services.table_format import (
    build_connection_card_rich_message,
    build_connections_list_rich_message,
)
from bot.states.forms import ConnectionForm

router = Router(name="connections")
logger = logging.getLogger(__name__)

DEFAULT_PORTS = {
    DbType.POSTGRES: 5432,
    DbType.CLICKHOUSE: 8123,
}


class IsConnectionCard(Filter):
    async def __call__(self, message: Message) -> bool:
        return looks_like_connection_card(message.text or "")


def _sql_mode_label(read_only: bool) -> str:
    return "только чтение" if read_only else "чтение и запись"


async def _show_connection_card(
    message: Message,
    conn: DbConnection,
    *,
    is_active: bool,
    edit: bool = False,
    notice: str | None = None,
) -> None:
    rich = build_connection_card_rich_message(
        conn,
        is_active=is_active,
        notice=notice,
    )
    if edit:
        try:
            await message.edit_text(rich_message=rich)
            return
        except TelegramBadRequest:
            pass
    await message.answer_rich(rich_message=rich)


async def _show_connections_list(
    message: Message,
    session: AsyncSession,
    user_id: int,
    *,
    edit: bool = False,
    notice: str | None = None,
) -> None:
    connections = await repo.list_connections(session, user_id)
    user = await repo.get_or_create_user(session, user_id)
    rich = build_connections_list_rich_message(
        connections,
        active_id=user.active_connection_id,
        notice=notice,
    )
    markup = connections_list_kb()
    if edit:
        try:
            await message.edit_text(rich_message=rich, reply_markup=markup)
            return
        except TelegramBadRequest:
            pass
    await message.answer_rich(rich_message=rich, reply_markup=markup)


async def _edit_or_answer(
    callback: CallbackQuery,
    text: str,
    reply_markup=None,
) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup)


@router.message(
    IsConnectionCard(),
    F.text,
    ~F.text.in_(MENU_TEXTS),
    ~F.text.startswith("/"),
)
async def import_connection_card(message: Message, state: FSMContext) -> None:
    try:
        parsed = parse_connection_card(message.text or "")
    except ConnectionCardParseError as exc:
        await message.answer(f"Не удалось разобрать карточку: {exc}")
        return

    await state.update_data(
        name=parsed.name,
        db_type=parsed.db_type,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        username=parsed.username,
        read_only=parsed.read_only,
    )
    await state.set_state(ConnectionForm.password)
    await message.answer(
        f"Карточка «{html.escape(parsed.name)}» распознана.\n"
        f"Режим SQL: {html.escape(_sql_mode_label(parsed.read_only))}.\n"
        "Введите пароль:",
        reply_markup=cancel_kb(),
    )


@router.message(Command("connections"))
@router.message(F.text == MENU_TEXT_CONNECTIONS)
async def list_connections_msg(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await _show_connections_list(message, session, message.from_user.id)


@router.callback_query(F.data.in_({"conn:list", "menu:connections"}))
async def list_connections_cb(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await _show_connections_list(
        callback.message,
        session,
        callback.from_user.id,
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("conn:view:"))
async def view_connection(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Подключение не найдено", show_alert=True)
        return
    user = await repo.get_or_create_user(session, callback.from_user.id)
    is_active = user.active_connection_id == conn.id
    await _show_connection_card(
        callback.message,
        conn,
        is_active=is_active,
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("conn:activate:"))
async def activate_connection(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Подключение не найдено", show_alert=True)
        return
    await repo.set_active_connection(session, callback.from_user.id, conn.id)
    logger.info("user=%s activate_connection id=%s", callback.from_user.id, conn.id)
    await _show_connection_card(
        callback.message,
        conn,
        is_active=True,
        edit=True,
    )
    await callback.answer("Подключение выбрано")


@router.callback_query(F.data == "conn:add")
async def add_connection_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ConnectionForm.db_type)
    await _edit_or_answer(callback, "Выберите тип БД:", db_type_kb())
    await callback.answer()


@router.callback_query(ConnectionForm.db_type, F.data.startswith("conn:type:"))
async def add_db_type(callback: CallbackQuery, state: FSMContext) -> None:
    db_type = callback.data.split(":")[-1]
    await state.update_data(db_type=db_type)
    await state.set_state(ConnectionForm.name)
    await callback.message.edit_text(
        "Введите название подключения (для списка):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ConnectionForm.name, F.text, ~F.text.in_(MENU_TEXTS))
async def add_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name or len(name) > 128:
        await message.answer("Название обязательно, до 128 символов.")
        return
    await state.update_data(name=name)
    await state.set_state(ConnectionForm.host)
    await message.answer("Введите host / IP:", reply_markup=cancel_kb())


@router.message(ConnectionForm.host, F.text, ~F.text.in_(MENU_TEXTS))
async def add_host(message: Message, state: FSMContext) -> None:
    host = (message.text or "").strip()
    if not host:
        await message.answer("Host не может быть пустым.")
        return
    await state.update_data(host=host)
    await state.set_state(ConnectionForm.port)
    data = await state.get_data()
    default_port = DEFAULT_PORTS.get(data["db_type"], 5432)
    await message.answer(
        f"Введите порт или нажмите кнопку (по умолчанию {default_port}):",
        reply_markup=skip_default_port_kb(),
    )


@router.callback_query(ConnectionForm.port, F.data == "conn:port:default")
async def add_port_default(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(port=DEFAULT_PORTS.get(data["db_type"], 5432))
    await state.set_state(ConnectionForm.database)
    await callback.message.answer("Введите имя базы данных:", reply_markup=cancel_kb())
    await callback.answer()


@router.message(ConnectionForm.port, F.text, ~F.text.in_(MENU_TEXTS))
async def add_port(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit():
        await message.answer("Порт должен быть числом.")
        return
    port = int(text)
    if not 1 <= port <= 65535:
        await message.answer("Порт вне диапазона 1–65535.")
        return
    await state.update_data(port=port)
    await state.set_state(ConnectionForm.database)
    await message.answer("Введите имя базы данных:", reply_markup=cancel_kb())


@router.message(ConnectionForm.database, F.text, ~F.text.in_(MENU_TEXTS))
async def add_database(message: Message, state: FSMContext) -> None:
    database = (message.text or "").strip()
    if not database:
        await message.answer("Имя БД не может быть пустым.")
        return
    await state.update_data(database=database)
    await state.set_state(ConnectionForm.username)
    await message.answer("Введите пользователя:", reply_markup=cancel_kb())


@router.message(ConnectionForm.username, F.text, ~F.text.in_(MENU_TEXTS))
async def add_username(message: Message, state: FSMContext) -> None:
    username = (message.text or "").strip()
    if not username:
        await message.answer("Пользователь не может быть пустым.")
        return
    await state.update_data(username=username)
    await state.set_state(ConnectionForm.password)
    await message.answer("Введите пароль:", reply_markup=cancel_kb())


@router.message(ConnectionForm.password, F.text, ~F.text.in_(MENU_TEXTS))
async def add_password(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
) -> None:
    password = message.text or ""
    try:
        await message.delete()
    except Exception:
        pass
    await state.update_data(password=password)
    data = await state.get_data()
    if "read_only" in data:
        status_msg = await message.answer("Проверяю подключение…")
        await _persist_draft_connection(
            user_id=message.from_user.id,
            data=data,
            read_only=bool(data["read_only"]),
            session=session,
            cipher=cipher,
            settings=settings,
            state=state,
            status_message=status_msg,
        )
        return
    await state.set_state(ConnectionForm.read_only)
    await message.answer(
        "Режим SQL для этого подключения:\n"
        "«Только чтение» запрещает изменение данных на уровне сессии.",
        reply_markup=read_only_choice_kb(),
    )


@router.callback_query(ConnectionForm.read_only, F.data.startswith("conn:readonly:"))
async def add_read_only(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
) -> None:
    read_only = callback.data.rsplit(":", 1)[-1] == "1"
    if callback.message is None:
        await callback.answer("Не удалось сохранить подключение", show_alert=True)
        return
    data = await state.get_data()
    await _persist_draft_connection(
        user_id=callback.from_user.id,
        data=data,
        read_only=read_only,
        session=session,
        cipher=cipher,
        settings=settings,
        state=state,
        status_message=callback.message,
    )
    await callback.answer()


async def _persist_draft_connection(
    *,
    user_id: int,
    data: dict[str, object],
    read_only: bool,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
    state: FSMContext,
    status_message: Message,
) -> None:
    required = ("name", "db_type", "host", "port", "database", "username", "password")
    if any(key not in data for key in required):
        await state.clear()
        await status_message.edit_text("Сессия истекла, добавьте подключение заново.")
        return

    encrypted = cipher.encrypt(str(data["password"]))
    draft = DbConnection(
        user_id=user_id,
        name=str(data["name"]),
        db_type=str(data["db_type"]),
        host=str(data["host"]),
        port=int(data["port"]),
        database=str(data["database"]),
        username=str(data["username"]),
        password_encrypted=encrypted,
        read_only=read_only,
    )

    try:
        await status_message.edit_text("Проверяю подключение…")
    except TelegramBadRequest:
        pass
    try:
        await test_connection(draft, cipher, settings.query_timeout_sec)
    except Exception as exc:
        logger.warning("user=%s connection_test_failed: %s", user_id, exc)
        await status_message.edit_text(
            f"Не удалось подключиться: {exc}\n"
            "Исправьте данные и добавьте подключение заново.",
        )
        await state.clear()
        return

    try:
        existing = await repo.get_connection_by_name(
            session,
            user_id,
            str(data["name"]),
        )
        if existing is None:
            conn = await repo.create_connection(
                session,
                user_id=user_id,
                name=str(data["name"]),
                db_type=str(data["db_type"]),
                host=str(data["host"]),
                port=int(data["port"]),
                database=str(data["database"]),
                username=str(data["username"]),
                password_encrypted=encrypted,
                read_only=read_only,
            )
            saved_as = "сохранено"
        else:
            conn = await repo.update_connection(
                session,
                existing,
                db_type=str(data["db_type"]),
                host=str(data["host"]),
                port=int(data["port"]),
                database=str(data["database"]),
                username=str(data["username"]),
                password_encrypted=encrypted,
                read_only=read_only,
            )
            saved_as = "обновлено"
    except Exception as exc:
        logger.exception("save_connection failed")
        await status_message.edit_text(f"Ошибка сохранения: {exc}")
        await state.clear()
        return

    await repo.set_active_connection(session, user_id, conn.id)
    await state.clear()
    logger.info("user=%s save_connection id=%s", user_id, conn.id)
    await _show_connection_card(
        status_message,
        conn,
        is_active=True,
        edit=True,
        notice=f"Подключение {saved_as} и выбрано как активное.",
    )


@router.callback_query(F.data.startswith("conn:edit:"))
async def edit_connection_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await _edit_or_answer(
        callback,
        "Что изменить?",
        connection_edit_fields_kb(conn.id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("conn:editfield:"))
async def edit_field_start(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    _, _, connection_id_s, field = callback.data.split(":", 3)
    connection_id = int(connection_id_s)
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    if field == "read_only":
        await callback.message.edit_text(
            "Режим SQL для этого подключения:",
            reply_markup=read_only_edit_kb(connection_id, conn.read_only),
        )
        await callback.answer()
        return
    await state.set_state(ConnectionForm.edit_field_value)
    await state.update_data(edit_connection_id=connection_id, edit_field=field)
    labels = {
        "host": "новый host/IP",
        "database": "новое имя БД",
        "username": "нового пользователя",
        "password": "новый пароль",
        "port": "новый порт",
        "name": "новое название",
    }
    await callback.message.answer(
        f"Введите {labels.get(field, field)}:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ConnectionForm.edit_field_value, F.text, ~F.text.in_(MENU_TEXTS))
async def edit_field_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    cipher: PasswordCipher,
    settings: Settings,
) -> None:
    data = await state.get_data()
    connection_id = int(data["edit_connection_id"])
    field = data["edit_field"]
    value = message.text or ""
    conn = await repo.get_connection(session, message.from_user.id, connection_id)
    if conn is None:
        await state.clear()
        await message.answer("Подключение не найдено.", reply_markup=main_menu_kb())
        return

    update_fields: dict[str, object] = {}
    if field == "port":
        if not value.strip().isdigit():
            await message.answer("Порт должен быть числом.")
            return
        port = int(value.strip())
        if not 1 <= port <= 65535:
            await message.answer("Порт вне диапазона.")
            return
        update_fields["port"] = port
    elif field == "password":
        update_fields["password_encrypted"] = cipher.encrypt(value)
        try:
            await message.delete()
        except Exception:
            pass
    else:
        cleaned = value.strip()
        if not cleaned:
            await message.answer("Значение не может быть пустым.")
            return
        update_fields[field] = cleaned

    await repo.update_connection(session, conn, **update_fields)
    await session.refresh(conn)

    try:
        await test_connection(conn, cipher, settings.query_timeout_sec)
        test_note = "Проверка подключения: OK"
    except Exception as exc:
        test_note = f"Проверка подключения не прошла: {exc}"

    user = await repo.get_or_create_user(session, message.from_user.id)
    await state.clear()
    logger.info(
        "user=%s edit_connection id=%s field=%s",
        message.from_user.id,
        connection_id,
        field,
    )
    await _show_connection_card(
        message,
        conn,
        is_active=user.active_connection_id == conn.id,
        notice=f"Обновлено.\n{test_note}",
    )


@router.callback_query(F.data.startswith("conn:setreadonly:"))
async def set_read_only(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, connection_id_s, value_s = callback.data.split(":")
    connection_id = int(connection_id_s)
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await repo.update_connection(session, conn, read_only=value_s == "1")
    user = await repo.get_or_create_user(session, callback.from_user.id)
    is_active = user.active_connection_id == conn.id
    logger.info(
        "user=%s edit_connection id=%s field=read_only value=%s",
        callback.from_user.id,
        connection_id,
        conn.read_only,
    )
    await _show_connection_card(
        callback.message,
        conn,
        is_active=is_active,
        edit=True,
    )
    await callback.answer("Режим обновлён")


@router.callback_query(F.data.regexp(re.compile(r"^conn:delete:\d+$")))
async def delete_connection_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await _edit_or_answer(
        callback,
        f"Удалить подключение «{html.escape(conn.name)}»? "
        "Избранные запросы этой БД тоже будут удалены.",
        confirm_delete_kb(conn.id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(re.compile(r"^conn:delete_confirm:\d+$")))
async def delete_connection_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    name = conn.name
    await repo.delete_connection(session, conn)
    logger.info("user=%s delete_connection id=%s", callback.from_user.id, connection_id)
    await _show_connections_list(
        callback.message,
        session,
        callback.from_user.id,
        edit=True,
        notice=f"Подключение «{name}» удалено.",
    )
    await callback.answer()
