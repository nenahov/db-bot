from aiogram import Router

from bot.handlers.connections import router as connections_router
from bot.handlers.favorites import router as favorites_router
from bot.handlers.queries import router as queries_router
from bot.handlers.start import router as start_router


def setup_routers() -> Router:
    root = Router()
    root.include_router(start_router)
    root.include_router(connections_router)
    root.include_router(queries_router)
    root.include_router(favorites_router)
    return root
