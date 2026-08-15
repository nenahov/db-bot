from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repositories as repo
from bot.db.models import DbConnection
from bot.keyboards.common import MENU_TEXT_CURRENT, main_menu_kb

router = Router()

MAIN_MENU_TEXT = (
    "Привет! Я бот-клиент для PostgreSQL и ClickHouse.\n"
    "Отправьте SQL-запрос одним сообщением — я выполню его на активном подключении.\n"
    "Или выберите действие:"
)


def _current_connection_text(conn: DbConnection) -> str:
    return (
        "Текущее подключение:\n"
        f"• {conn.name} ({conn.db_type})\n"
        f"• {conn.host}:{conn.port}/{conn.database}\n"
        f"• user: {conn.username}"
    )


async def _show_main_menu(message: Message) -> None:
    await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_kb())


async def _edit_or_answer(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=main_menu_kb())
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=main_menu_kb())


@router.message(CommandStart())
@router.message(Command("menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _show_main_menu(message)


@router.message(F.text == MENU_TEXT_CURRENT)
async def show_current_msg(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    conn = await repo.get_active_connection(session, message.from_user.id)
    if conn is None:
        await message.answer(
            "Активное подключение не выбрано.\nОткройте «Подключения».",
            reply_markup=main_menu_kb(),
        )
        return
    await message.answer(_current_connection_text(conn), reply_markup=main_menu_kb())


@router.callback_query(F.data == "menu:current")
async def show_current(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    conn = await repo.get_active_connection(session, callback.from_user.id)
    if conn is None:
        await _edit_or_answer(
            callback,
            "Активное подключение не выбрано.\nОткройте «Подключения».",
        )
        await callback.answer()
        return
    await _edit_or_answer(callback, _current_connection_text(conn))
    await callback.answer()


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_or_answer(callback, MAIN_MENU_TEXT)
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit_or_answer(callback, "Отменено.")
    await callback.answer()
