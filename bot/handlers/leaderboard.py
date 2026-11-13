from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from handlers.db import get_leaderboard, get_user
from handlers.locales import get_text

router = Router()

def get_lb_kb(active="today", lang="ru"):
    kb = [
        [InlineKeyboardButton(text=get_text("tf_today", lang).capitalize() if active != "today" else f"✅ {get_text('tf_today', lang).capitalize()}", callback_data="lb_today"),
         InlineKeyboardButton(text=get_text("tf_week", lang).capitalize() if active != "week" else f"✅ {get_text('tf_week', lang).capitalize()}", callback_data="lb_week")],
        [InlineKeyboardButton(text=get_text("tf_month", lang).capitalize() if active != "month" else f"✅ {get_text('tf_month', lang).capitalize()}", callback_data="lb_month")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def format_lb(tf, lang):
    leaders = get_leaderboard(tf)
    if not leaders: return get_text("top_empty", lang)
    
    tf_name = get_text(f"tf_{tf}", lang)
    text = get_text("top_title", lang, tf=tf_name)
    
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(leaders):
        medal = medals[i] if i < 3 else f"{i+1}."
        text += f"{medal} {row['first_name']} — {row['total_points']} pts\n"
    return text

@router.callback_query(F.data == "menu_top")
async def show_top(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    await callback.message.edit_text(format_lb("today", lang), reply_markup=get_lb_kb("today", lang), parse_mode="HTML")

@router.callback_query(F.data.startswith("lb_"))
async def switch_lb(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    tf = callback.data.split("_")[1]
    await callback.message.edit_text(format_lb(tf, lang), reply_markup=get_lb_kb(tf, lang), parse_mode="HTML")
    await callback.answer()