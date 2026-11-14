import html
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from handlers.db import get_or_create_user
from handlers.locales import get_text

router = Router()


@router.callback_query(F.data == "menu_profile")
async def show_profile(callback: CallbackQuery):
    user = get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    if not user:
        await callback.answer(get_text("error_generic", "ru"), show_alert=True)
        return
    lang = user["lang_pair"].split("-")[-1] if user.get("lang_pair") else "ru"
    text = get_text(
        "profile", lang,
        name=html.escape(user.get("first_name") or "User"),
        login=html.escape(user.get("site_login") or "---"),
        level=user.get("level", 1),
        points=user.get("points", 0),
        lang_pair=html.escape(user.get("lang_pair") or "---"),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()