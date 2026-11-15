from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import add_user, get_or_create_user, update_lang_pair, update_credentials
from handlers.locales import get_text
from config import WEBAPP_URL

rt = Router()


class RegState(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()


def get_main_menu(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton(text=get_text("btn_daily", lang), callback_data="menu_daily")],
        [InlineKeyboardButton(text=get_text("btn_practice", lang), callback_data="menu_practice")],
        [InlineKeyboardButton(text=get_text("btn_top", lang), callback_data="menu_top")],
        [InlineKeyboardButton(text=get_text("btn_profile", lang), callback_data="menu_profile")],
        [InlineKeyboardButton(text=get_text("btn_settings", lang), callback_data="menu_settings")],
    ])


def get_lang_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="set_lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🇰🇿 Қазақ", callback_data="set_lang_kk")],
    ])


def _lang_of(user):
    if user and user.get("lang_pair"):
        return user["lang_pair"].split("-")[-1]
    return "ru"


@rt.message(Command("app"))
async def open_app(message: Message):
    user = get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    lang = _lang_of(user)
    await message.answer(
        f"{get_text('menu', lang)}\n\n🎮 Открыть приложение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎮 Открыть приложение", web_app=WebAppInfo(url=WEBAPP_URL))]
        ]),
    )


@rt.message(Command("cancel"))
async def cancel_handler(message: Message, state: FSMContext):
    user = get_or_create_user(
        message.from_user.id, message.from_user.username, message.from_user.first_name
    )
    lang = _lang_of(user)
    current = await state.get_state()
    if current is None:
        await message.answer(get_text("nothing_to_cancel", lang))
        if user:
            await message.answer(get_text("menu", lang), reply_markup=get_main_menu(lang))
        return
    await state.clear()
    await message.answer(get_text("cancel_done", lang), reply_markup=get_main_menu(lang))


@rt.message(CommandStart())
async def start_menu(message: Message):
    add_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    user = get_or_create_user(message.from_user.id)
    lang = _lang_of(user)

    if not user or not user.get("lang_pair"):
        await message.answer(get_text("welcome", "ru"), reply_markup=get_lang_menu())
    elif not user.get("site_login"):
        await message.answer(get_text("enter_login", lang))
    else:
        await message.answer(get_text("welcome_back", lang), reply_markup=get_main_menu(lang))


@rt.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback: CallbackQuery, state: FSMContext):
    lang_code = callback.data.split("_")[2]
    update_lang_pair(callback.from_user.id, f"ba-{lang_code}")
    await callback.message.edit_text(get_text("lang_updated", lang_code))
    user = get_or_create_user(callback.from_user.id)
    if not user or not user.get("site_login"):
        await callback.message.answer(get_text("enter_login", lang_code))
        await state.set_state(RegState.waiting_for_login)
    else:
        await callback.message.answer(get_text("welcome_back", lang_code), reply_markup=get_main_menu(lang_code))
    await callback.answer()


@rt.message(RegState.waiting_for_login)
async def process_login(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 3 or len(text) > 64:
        await message.answer("Логин должен быть от 3 до 64 символов. /cancel для отмены.")
        return
    await state.update_data(site_login=text)
    user = get_or_create_user(message.from_user.id)
    await message.answer(get_text("enter_password", _lang_of(user)))
    await state.set_state(RegState.waiting_for_password)


@rt.message(RegState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if len(text) < 4 or len(text) > 128:
        await message.answer("Пароль должен быть от 4 до 128 символов. /cancel для отмены.")
        return
    data = await state.get_data()
    update_credentials(message.from_user.id, data.get("site_login"), text)
    await state.clear()
    user = get_or_create_user(message.from_user.id)
    await message.answer(get_text("reg_success", _lang_of(user)), reply_markup=get_main_menu(_lang_of(user)))


@rt.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user = get_or_create_user(callback.from_user.id)
    lang = _lang_of(user)
    await callback.message.edit_text(get_text("menu", lang), reply_markup=get_main_menu(lang))
    await callback.answer()


@rt.callback_query(F.data == "menu_settings")
async def show_settings(callback: CallbackQuery):
    user = get_or_create_user(callback.from_user.id)
    await callback.message.edit_text(
        get_text("settings", _lang_of(user)), reply_markup=get_lang_menu(), parse_mode="HTML"
    )
    await callback.answer()