from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from handlers.db import add_user, get_user

rt = Router()

@rt.message(CommandStart())
async def start_menu(message: Message):
    user = message.from_user
    
    add_user(
        user_id=user.id, 
        username=user.username or "Нет_Ника",
        first_name=user.first_name
    )
    
    db_user = get_user(user.id)
    progress = db_user['progress'] if db_user else 0
    
    await message.answer(
        f"Привет, {user.first_name}!\n"
        f"Твой прогресс в башкирском: {progress} очков.\n"
        f"Погнали учиться!"
    )

@rt.message(F.text == "/help")
async def help_menu(message: Message):
    await message.answer('Меню помощи')