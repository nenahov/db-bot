from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.common import main_menu_kb

router = Router()

MAIN_MENU_TEXT = (
    "Привет! Я бот-клиент для PostgreSQL и ClickHouse.\n"
    "Отправьте SQL-запрос одним сообщением — я выполню его на активном подключении.\n"
    "Или выберите действие:"
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
