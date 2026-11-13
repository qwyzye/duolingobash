import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.ai import generate_task
from handlers.db import get_user, update_progress, add_learned_word, get_user_words

router = Router()

class LessonState(StatesGroup):
    waiting_for_answer = State()

@router.message(Command("lesson"))
async def start_lesson(message: Message, state: FSMContext):
    msg = await message.answer("⏳ Генерирую задание, подожди пару секунд...")
    
    user_data = get_user(message.from_user.id)
    level = user_data.get('level', 1) if user_data else 1
    known_words = get_user_words(message.from_user.id)

    task_types = [
        "word_ru_bash",       # Перевод слова с ру на баш
        "word_bash_ru",       # Перевод слова с баш на ру
        "sentence_ru_bash",   # Перевод предложения с ру на баш
        "sentence_bash_ru",   # Перевод предложения с баш на ру
        "fill_blank",         # Вставить пропущенное слово
        "make_sentence",      # Составить предложение из слов
        "find_extra"          # Найти лишнее слово
    ]
    chosen_type = random.choice(task_types)
    
    task = await generate_task(chosen_type, level=level, known_words=known_words)
    
    if not task:
        await msg.edit_text("❌ Ошибка генерации задания. Попробуй позже.")
        return

    # Сохраняем в память
    await state.update_data(
        correct_answer=task.get('correct_answer'),
        new_word=task.get('new_word')
    )
    await state.set_state(LessonState.waiting_for_answer)

    options = task.get('options', [])
    keyboard = []
    
    if options:
        random.shuffle(options) # Перемешиваем
        for opt in options:
            keyboard.append([InlineKeyboardButton(text=opt, callback_data=f"ans_{opt}")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard) if keyboard else None
    
    await msg.edit_text(f"📝 Задание:\n\n{task.get('question')}", reply_markup=markup)

@router.callback_query(F.data.startswith("ans_"), LessonState.waiting_for_answer)
async def check_answer(callback: CallbackQuery, state: FSMContext):
    user_answer = callback.data.replace("ans_", "", 1) # Безопасное извлечение
    
    data = await state.get_data()
    correct_answer = data.get('correct_answer')
    new_word = data.get('new_word')
    
    if correct_answer and user_answer.lower().strip() == correct_answer.lower().strip():
        await callback.message.edit_text("✅ Правильно! Молодец. +10 очков.")
        update_progress(callback.from_user.id, 10)
        
        if new_word and new_word != "null" and new_word is not None:
            add_learned_word(callback.from_user.id, new_word, correct_answer)
            await callback.message.answer(f"📖 Слово «{new_word}» добавлено в твой словарь!")
            
    else:
        await callback.message.edit_text(f"❌ Неправильно.\nПравильный ответ: {correct_answer}")
    
    await state.clear()
    await callback.answer()