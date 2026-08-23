from aiogram import F, Router
from aiogram.enums import ChatType

from bot.handlers.auth import router as auth_router
from bot.handlers.connections import router as connections_router
from bot.handlers.favorites import router as favorites_router
from bot.handlers.queries import router as queries_router
from bot.handlers.start import router as start_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(auth_router)

    private = Router()
    private.message.filter(F.chat.type == ChatType.PRIVATE)
    private.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
    private.include_router(start_router)
    private.include_router(connections_router)
    private.include_router(queries_router)
    private.include_router(favorites_router)
    root.include_router(private)
    return root
