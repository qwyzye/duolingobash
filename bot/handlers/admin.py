import html
import sqlite3
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command

from config import ADMIN_ID
from handlers.db import CONTENT_DB, get_dictionary_review

router = Router()


@router.message(Command("review"))
async def show_expert_review(message: Message):
    if not ADMIN_ID or message.from_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect(str(CONTENT_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT t.id, t.translation, t.lang_pair, t.text_ba
           FROM translations t
           WHERE t.status = 'expert_review'
           ORDER BY t.id DESC LIMIT 10"""
    ).fetchall()
    conn.close()

    if not rows:
        await message.answer("Спорных переводов фрагментов нет.")
    else:
        for r in rows:
            text = (
                f"<b>ID:</b> {r['id']}\n"
                f"<b>Язык:</b> {html.escape(r['lang_pair'] or '?')}\n"
                f"<b>Оригинал:</b> {html.escape(r['text_ba'] or '')}\n"
                f"<b>Перевод:</b> {html.escape(r['translation'] or '')}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"review_approve_{r['id']}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"review_reject_{r['id']}"),
            ]])
            await message.answer(text, reply_markup=kb, parse_mode="HTML")

    dict_rows = get_dictionary_review(limit=10)
    if dict_rows:
        await message.answer("<b>⚠️ Предложенные переводы слов:</b>", parse_mode="HTML")
        for r in dict_rows:
            txt = (
                f"<b>ID:</b> {r['id']}\n"
                f"<b>Слово:</b> {html.escape(r['word'])}\n"
                f"<b>Вариант:</b> {html.escape(r['translation'])}\n"
                f"<b>Язык:</b> {html.escape(r['lang_pair'])}"
            )
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="✅ Принять", callback_data=f"dict_approve_{r['id']}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"dict_reject_{r['id']}"),
            ]])
            await message.answer(txt, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("review_"))
async def handle_review(callback: CallbackQuery):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав", show_alert=True)
        return
    parts = callback.data.split("_")
    action, rid = parts[1], int(parts[2])
    conn = sqlite3.connect(str(CONTENT_DB))
    if action == "approve":
        conn.execute("UPDATE translations SET status='confirmed' WHERE id=?", (rid,))
    else:
        conn.execute("UPDATE translations SET status='rejected' WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ Принято" if action == "approve" else "❌ Отклонено")
    await callback.answer()


@router.callback_query(F.data.startswith("dict_"))
async def handle_dict_review(callback: CallbackQuery):
    if not ADMIN_ID or callback.from_user.id != ADMIN_ID:
        await callback.answer("Нет прав", show_alert=True)
        return
    parts = callback.data.split("_")
    action, rid = parts[1], int(parts[2])
    conn = sqlite3.connect(str(CONTENT_DB))
    if action == "approve":
        conn.execute("UPDATE dictionary SET status='confirmed', is_parsed=1 WHERE id=?", (rid,))
    else:
        conn.execute("UPDATE dictionary SET status='rejected' WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    await callback.message.edit_text("✅ Принято" if action == "approve" else "❌ Отклонено")
    await callback.answer()