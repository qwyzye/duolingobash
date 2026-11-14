import html
import random
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.ai import generate_task
from handlers.db import get_or_create_user, update_progress, add_learned_word, get_user_words

router = Router()


class LessonState(StatesGroup):
    waiting_for_answer = State()


@router.message(Command("lesson"))
async def start_lesson(message: Message, state: FSMContext):
    user = get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    level = user.get("level", 1) if user else 1
    known = get_user_words(message.from_user.id)

    msg = await message.answer("⏳ Генерирую задание...")
    task_type = random.choice([
        "word_ru_bash", "word_bash_ru", "sentence_ru_bash", "sentence_bash_ru",
        "fill_blank", "make_sentence", "find_extra",
    ])
    task = await generate_task(task_type, level=level, known_words=known)
    if not task:
        await msg.edit_text("❌ Ошибка генерации задания. Попробуйте позже.")
        return

    options = task.get("options") or []
    await state.update_data(
        correct_answer=task.get("correct_answer"),
        new_word=task.get("new_word"),
        options=options,
    )
    await state.set_state(LessonState.waiting_for_answer)

    kb = []
    if options:
        random.shuffle(options)
        await state.update_data(options=options)
        for i, opt in enumerate(options):
            kb.append([InlineKeyboardButton(text=str(opt)[:60], callback_data=f"ans_{i}")])
    markup = InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

    await msg.edit_text(f"📝 Задание:\n\n{html.escape(task.get('question', ''))}", reply_markup=markup)


@router.callback_query(F.data.startswith("ans_"), LessonState.waiting_for_answer)
async def check_answer(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    options = data.get("options") or []
    correct = data.get("correct_answer")
    new_word = data.get("new_word")

    try:
        idx = int(callback.data.split("_", 1)[1])
        user_answer = options[idx]
    except (IndexError, ValueError):
        await callback.answer("Ошибка варианта. Попробуйте /lesson заново.", show_alert=True)
        await state.clear()
        return

    if correct and str(user_answer).strip().lower() == str(correct).strip().lower():
        await callback.message.edit_text("✅ Правильно! +10 очков.")
        update_progress(callback.from_user.id, 10)
        if new_word and new_word != "null":
            add_learned_word(callback.from_user.id, new_word, correct)
            await callback.message.answer(f"📖 Слово «{html.escape(str(new_word))}» добавлено в словарь.")
    else:
        await callback.message.edit_text(f"❌ Неправильно.\nПравильный ответ: {html.escape(str(correct))}")

    await state.clear()
    await callback.answer()