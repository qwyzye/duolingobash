from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import add_user, get_user, update_lang_pair, update_credentials
from handlers.locales import get_text

rt = Router()

class RegState(StatesGroup):
    waiting_for_login = State()
    waiting_for_password = State()

def get_main_menu(lang):
    kb = [
        [InlineKeyboardButton(text=get_text("btn_daily", lang), callback_data="menu_daily")],
        [InlineKeyboardButton(text=get_text("btn_practice", lang), callback_data="menu_practice")],
        [InlineKeyboardButton(text=get_text("btn_top", lang), callback_data="menu_top")],
        [InlineKeyboardButton(text=get_text("btn_profile", lang), callback_data="menu_profile")],
        [InlineKeyboardButton(text=get_text("btn_settings", lang), callback_data="menu_settings")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def get_lang_menu():
    kb = [
        [InlineKeyboardButton(text="🇷🇺 Русский / Russian / Орыс", callback_data="set_lang_ru")],
        [InlineKeyboardButton(text="🇬🇧 Английский / English / Ағылшын", callback_data="set_lang_en")],
        [InlineKeyboardButton(text="🇰🇿 Казахский / Kazakh / Қазақ", callback_data="set_lang_kk")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@rt.message(CommandStart())
async def start_menu(message: Message):
    add_user(message.from_user.id, message.from_user.username or "NoName", message.from_user.first_name)
    user = get_user(message.from_user.id)
    
    # Определяем язык (по умолчанию ru)
    lang_code = "ru"
    if user.get('lang_pair'):
        lang_code = user['lang_pair'].split("-")[1]
    
    if not user.get('lang_pair'):
        await message.answer(get_text("welcome", "ru"), reply_markup=get_lang_menu())
    elif not user.get('site_login'):
        await message.answer(get_text("enter_login", lang_code))
    else:
        await message.answer(get_text("welcome_back", lang_code), reply_markup=get_main_menu(lang_code))

@rt.callback_query(F.data.startswith("set_lang_"))
async def set_language(callback: CallbackQuery, state: FSMContext):
    lang_code = callback.data.split("_")[2]
    update_lang_pair(callback.from_user.id, f"ba-{lang_code}")
    
    # Сразу показываем интерфейс на новом языке
    await callback.message.edit_text(get_text("lang_updated", lang_code))
    
    user = get_user(callback.from_user.id)
    if not user.get('site_login'):
        await callback.message.answer(get_text("enter_login", lang_code))
        await state.set_state(RegState.waiting_for_login)
    else:
        await callback.message.answer(get_text("welcome_back", lang_code), reply_markup=get_main_menu(lang_code))
        
    await callback.answer()

@rt.message(RegState.waiting_for_login)
async def process_login(message: Message, state: FSMContext):
    await state.update_data(site_login=message.text)
    user = get_user(message.from_user.id)
    lang_code = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    await message.answer(get_text("enter_password", lang_code))
    await state.set_state(RegState.waiting_for_password)

@rt.message(RegState.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    data = await state.get_data()
    login = data.get('site_login')
    
    update_credentials(message.from_user.id, login, message.text)
    await state.clear()
    
    user = get_user(message.from_user.id)
    lang_code = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    await message.answer(
        get_text("reg_success", lang_code), 
        reply_markup=get_main_menu(lang_code)
    )

@rt.callback_query(F.data == "menu_main")
async def back_to_main(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang_code = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    await callback.message.edit_text(get_text("menu", lang_code), reply_markup=get_main_menu(lang_code))
    await callback.answer()

@rt.callback_query(F.data == "menu_settings")
async def show_settings(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang_code = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    await callback.message.edit_text(get_text("settings", lang_code), reply_markup=get_lang_menu(), parse_mode="HTML")