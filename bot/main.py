import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import get_settings
from bot.db.session import close_db, get_session_factory, init_db
from bot.handlers import setup_routers
from bot.logging_setup import setup_logging
from bot.middlewares.action_log import ActionLogMiddleware
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.services.crypto import PasswordCipher
from bot.services.membership import MembershipCache
from bot.services.result_cache import ResultCache

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_dir)

    await init_db(settings.sqlite_path)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())

    cipher = PasswordCipher(settings.encryption_key)
    result_cache = ResultCache(settings.result_cache_ttl_sec)
    membership_cache = MembershipCache(settings.auth_cache_ttl_sec)

    session_factory = get_session_factory()
    dp.update.middleware(ActionLogMiddleware())
    dp.update.middleware(AuthMiddleware())
    dp.update.middleware(DbSessionMiddleware(session_factory))

    dp.include_router(setup_routers())

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="menu", description="Главное меню"),
            BotCommand(command="connections", description="Подключения"),
            BotCommand(command="favorites", description="Избранное"),
        ]
    )

    logger.info("Bot starting (polling)")
    try:
        await dp.start_polling(
            bot,
            settings=settings,
            cipher=cipher,
            result_cache=result_cache,
            membership_cache=membership_cache,
        )
    finally:
        await close_db()
        await bot.session.close()


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
