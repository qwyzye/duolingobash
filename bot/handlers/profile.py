from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from handlers.db import get_user
from handlers.locales import get_text

router = Router()

@router.callback_query(F.data == "menu_profile")
async def show_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    text = get_text("profile", lang, 
                    name=user['first_name'], 
                    login=user.get('site_login', '---'), 
                    level=user['level'], 
                    points=user['points'], 
                    lang_pair=user.get('lang_pair', '---'))
                    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")