from aiogram import Router
from aiogram.types import Message
from aiogram.filters import Command
import sqlite3

router = Router()
ADMIN_ID = 8780490228 # <-- ТВОЙ ID

@router.message(Command("review"))
async def show_expert_review(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
        
    conn = sqlite3.connect("bashlingo.db")
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.id, f.text_ba, t.translation, u.first_name 
        FROM translations t
        JOIN fragments f ON t.fragment_id = f.fragment_id
        JOIN users u ON t.user_id = u.user_id
        WHERE t.status = 'expert_review'
        LIMIT 10
    """)
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        await message.answer("Спорных переводов нет.")
        return
        
    text = "<b>⚠️ Спорные переводы (на проверке):</b>\n\n"
    for row in rows:
        text += f"<b>Оригинал:</b> {row['text_ba']}\n"
        text += f"<b>Предложенный перевод ({row['first_name']}):</b> {row['translation']}\n"
        text += f"ID: {row['id']}\n\n"
        
    await message.answer(text, parse_mode="HTML")