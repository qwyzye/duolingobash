import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.types import ErrorEvent, MenuButtonWebApp, WebAppInfo
from aiogram.exceptions import TelegramBadRequest

from config import TOKEN, WEBAPP_URL
from handlers.db import init_db
from handlers.start import rt as start_router
from handlers.daily import router as daily_router
from handlers.practice import router as practice_router
from handlers.lessons import router as lessons_router
from handlers.leaderboard import router as leaderboard_router
from handlers.profile import router as profile_router
from handlers.admin import router as admin_router
from storage import SQLiteFSMStorage
from api.main import start_api

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

dp = Dispatcher(storage=SQLiteFSMStorage("fsm_states.db"))


@dp.errors()
async def error_handler(event: ErrorEvent):
    logger.exception("Unhandled error: %s", event.exception, exc_info=event.exception)
    update = event.update
    try:
        if update.callback_query:
            await update.callback_query.answer("⚠️ Произошла ошибка. Попробуйте позже.", show_alert=True)
        elif update.message:
            await update.message.answer("⚠️ Произошла ошибка. Попробуйте позже.")
    except TelegramBadRequest:
        pass
    except Exception:
        logger.exception("error_handler failed")


async def main():
    init_db()

    dp.include_router(start_router)
    dp.include_router(daily_router)
    dp.include_router(practice_router)
    dp.include_router(lessons_router)
    dp.include_router(leaderboard_router)
    dp.include_router(profile_router)
    dp.include_router(admin_router)

    runner = await start_api()

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="🎮 Учить",
                web_app=WebAppInfo(url=WEBAPP_URL),
            )
        )
        logger.info("MenuButton Mini App установлен: %s", WEBAPP_URL)
    except Exception:
        logger.exception("set_chat_menu_button failed")

    logger.info("Бот запущен...")
    try:
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Остановлено.")