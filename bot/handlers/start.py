from aiogram import Router, F
from aiogram.types import Message

rt = Router()

@rt.message(F.text == "/start")
async def start_menu(message : Message):
    await message.answer('Привет')

@rt.message()

@rt.message(F.text == "/help")
async def help_menu(message : Message):
    await message.answer('Меню помощи')