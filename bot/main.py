import asyncio


from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.enums import ParseMode

from handlers.start import rt as start_router
from handlers.db import init_db

TOKEN = "9207208443:AAGV-OXvF5dxS79pVKP6oMvX0a3ZH-fbXtc"

dp = Dispatcher()


async def main():
    init_db()
    dp.include_router(start_router)
    bot = Bot(token=TOKEN)
    await dp.start_polling(bot)











if __name__ == "__main__":
    asyncio.run(main())