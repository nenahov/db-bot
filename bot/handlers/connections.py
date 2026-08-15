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
    connection_card_kb,
    connection_edit_fields_kb,
    connections_list_kb,
    db_type_kb,
    main_menu_kb,
    skip_default_port_kb,
)
from bot.services.connection_card import (
    ConnectionCardParseError,
    looks_like_connection_card,
    parse_connection_card,
)
from bot.services.crypto import PasswordCipher
from bot.services.executors import test_connection
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


def format_connection_card(conn: DbConnection, is_active: bool) -> str:
    active = "да" if is_active else "нет"
    return (
        f"<b>{html.escape(conn.name)}</b>\n"
        f"Тип: <code>{html.escape(conn.db_type)}</code>\n"
        f"Хост: <code>{html.escape(conn.host)}:{conn.port}</code>\n"
        f"БД: <code>{html.escape(conn.database)}</code>\n"
        f"Пользователь: <code>{html.escape(conn.username)}</code>\n"
        f"Пароль: <code>••••</code>\n"
        f"Активно: {active}"
    )


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
    )
    await state.set_state(ConnectionForm.password)
    await message.answer(
        f"Карточка «{html.escape(parsed.name)}» распознана.\nВведите пароль:",
        reply_markup=cancel_kb(),
    )


@router.message(Command("connections"))
@router.message(F.text == MENU_TEXT_CONNECTIONS)
async def list_connections_msg(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    connections = await repo.list_connections(session, message.from_user.id)
    text = "Выберите подключение:" if connections else "Подключений пока нет. Добавьте первое."
    await message.answer(text, reply_markup=connections_list_kb(connections))


@router.callback_query(F.data.in_({"conn:list", "menu:connections"}))
async def list_connections_cb(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    connections = await repo.list_connections(session, callback.from_user.id)
    text = "Выберите подключение:" if connections else "Подключений пока нет. Добавьте первое."
    try:
        await callback.message.edit_text(text, reply_markup=connections_list_kb(connections))
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=connections_list_kb(connections))
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
    await callback.message.edit_text(
        format_connection_card(conn, is_active),
        reply_markup=connection_card_kb(conn.id, is_active),
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
    await callback.message.edit_text(
        format_connection_card(conn, True),
        reply_markup=connection_card_kb(conn.id, True),
    )
    await callback.answer("Подключение выбрано")


@router.callback_query(F.data == "conn:add")
async def add_connection_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ConnectionForm.db_type)
    await callback.message.edit_text("Выберите тип БД:", reply_markup=db_type_kb())
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
    data = await state.get_data()
    encrypted = cipher.encrypt(password)

    # Try to delete password message for privacy
    try:
        await message.delete()
    except Exception:
        pass

    draft = DbConnection(
        user_id=message.from_user.id,
        name=data["name"],
        db_type=data["db_type"],
        host=data["host"],
        port=int(data["port"]),
        database=data["database"],
        username=data["username"],
        password_encrypted=encrypted,
    )

    status_msg = await message.answer("Проверяю подключение…")
    try:
        await test_connection(draft, cipher, settings.query_timeout_sec)
    except Exception as exc:
        logger.warning("user=%s connection_test_failed: %s", message.from_user.id, exc)
        await status_msg.edit_text(
            f"Не удалось подключиться: {exc}\n"
            "Исправьте данные и добавьте подключение заново.",
        )
        await state.clear()
        return

    try:
        existing = await repo.get_connection_by_name(
            session,
            message.from_user.id,
            data["name"],
        )
        if existing is None:
            conn = await repo.create_connection(
                session,
                user_id=message.from_user.id,
                name=data["name"],
                db_type=data["db_type"],
                host=data["host"],
                port=int(data["port"]),
                database=data["database"],
                username=data["username"],
                password_encrypted=encrypted,
            )
            saved_as = "сохранено"
        else:
            conn = await repo.update_connection(
                session,
                existing,
                db_type=data["db_type"],
                host=data["host"],
                port=int(data["port"]),
                database=data["database"],
                username=data["username"],
                password_encrypted=encrypted,
            )
            saved_as = "обновлено"
    except Exception as exc:
        logger.exception("save_connection failed")
        await status_msg.edit_text(f"Ошибка сохранения: {exc}")
        await state.clear()
        return

    await repo.set_active_connection(session, message.from_user.id, conn.id)
    await state.clear()
    logger.info("user=%s save_connection id=%s", message.from_user.id, conn.id)
    await status_msg.edit_text(
        f"Подключение {saved_as} и выбрано как активное.\n\n"
        + format_connection_card(conn, True),
        reply_markup=connection_card_kb(conn.id, True),
    )


@router.callback_query(F.data.startswith("conn:edit:"))
async def edit_connection_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.edit_text(
        "Что изменить?",
        reply_markup=connection_edit_fields_kb(conn.id),
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
    await message.answer(
        f"Обновлено.\n{test_note}\n\n"
        + format_connection_card(conn, user.active_connection_id == conn.id),
        reply_markup=connection_card_kb(conn.id, user.active_connection_id == conn.id),
    )


@router.callback_query(F.data.regexp(re.compile(r"^conn:delete:\d+$")))
async def delete_connection_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    connection_id = int(callback.data.split(":")[-1])
    conn = await repo.get_connection(session, callback.from_user.id, connection_id)
    if conn is None:
        await callback.answer("Не найдено", show_alert=True)
        return
    await callback.message.edit_text(
        f"Удалить подключение «{html.escape(conn.name)}»? "
        "Избранные запросы этой БД тоже будут удалены.",
        reply_markup=confirm_delete_kb(conn.id),
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
    connections = await repo.list_connections(session, callback.from_user.id)
    await callback.message.edit_text(
        f"Подключение «{name}» удалено.",
        reply_markup=connections_list_kb(connections),
    )
    await callback.answer()
