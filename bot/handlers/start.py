from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repositories as repo
from bot.keyboards.common import MENU_TEXT_CURRENT, main_menu_kb

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет! Я бот-клиент для PostgreSQL и ClickHouse.\n"
        "Выберите действие в меню.",
        reply_markup=main_menu_kb(),
    )


@router.message(Command("menu"))
@router.message(F.text == MENU_TEXT_CURRENT)
async def show_current(
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
    await message.answer(
        "Текущее подключение:\n"
        f"• {conn.name} ({conn.db_type})\n"
        f"• {conn.host}:{conn.port}/{conn.database}\n"
        f"• user: {conn.username}",
        reply_markup=main_menu_kb(),
    )


@router.callback_query(F.data == "menu:home")
async def cb_home(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("Отменено.", reply_markup=main_menu_kb())
    await callback.answer()
