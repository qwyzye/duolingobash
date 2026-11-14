import html
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from handlers.db import get_leaderboard, get_or_create_user
from handlers.locales import get_text

router = Router()


def _lang(user):
    return user["lang_pair"].split("-")[-1] if user and user.get("lang_pair") else "ru"


def _kb(active, lang):
    def btn(key, tf):
        text = get_text(key, lang).capitalize()
        if active == tf:
            text = f"✅ {text}"
        return InlineKeyboardButton(text=text, callback_data=f"lb_{tf}")
    return InlineKeyboardMarkup(inline_keyboard=[
        [btn("tf_today", "today"), btn("tf_week", "week")],
        [btn("tf_month", "month"), btn("tf_year", "year")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")],
    ])


def _format(tf, lang):
    leaders = get_leaderboard(tf)
    if not leaders:
        return get_text("top_empty", lang)
    text = get_text("top_title", lang, tf=get_text(f"tf_{tf}", lang))
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(leaders):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        text += f"{prefix} {html.escape(row['first_name'] or 'User')} — {row['total_points']} pts\n"
    return text


@router.callback_query(F.data == "menu_top")
async def show_top(callback: CallbackQuery):
    user = get_or_create_user(callback.from_user.id)
    lang = _lang(user)
    await callback.message.edit_text(_format("today", lang), reply_markup=_kb("today", lang), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("lb_"))
async def switch_lb(callback: CallbackQuery):
    user = get_or_create_user(callback.from_user.id)
    lang = _lang(user)
    tf = callback.data.split("_", 1)[1]
    await callback.message.edit_text(_format(tf, lang), reply_markup=_kb(tf, lang), parse_mode="HTML")
    await callback.answer()