import asyncio
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties

from config import TOKEN
from handlers.db import init_db
from handlers.start import rt as start_router
from handlers.daily import router as daily_router
from handlers.practice import router as practice_router
from handlers.leaderboard import router as leaderboard_router
from handlers.profile import router as profile_router
from handlers.admin import router as admin_router

dp = Dispatcher(storage=MemoryStorage())

async def main():
    init_db()
    dp.include_router(start_router)
    dp.include_router(daily_router)
    dp.include_router(practice_router)
    dp.include_router(leaderboard_router)
    dp.include_router(profile_router)
    dp.include_router(admin_router)
    
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот выключен.")