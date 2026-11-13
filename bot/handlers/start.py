from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from handlers.db import add_user, get_user

rt = Router()

@rt.message(CommandStart())
async def start_menu(message: Message):
    user = message.from_user
    add_user(user.id, user.username or "Нет_Ника", user.first_name)
    
    db_user = get_user(user.id)
    progress = db_user.get('progress', 0) if db_user else 0
    level = db_user.get('level', 1) if db_user else 1
    
    await message.answer(
        f"Привет, {user.first_name}!\n"
        f"📊 Твой прогресс: {progress} очков.\n"
        f"🎓 Твой уровень: {level}\n\n"
        f"Напиши /lesson чтобы начать!"
    )

@rt.message(F.text == "/help")
async def help_menu(message: Message):
    await message.answer('Меню помощи')