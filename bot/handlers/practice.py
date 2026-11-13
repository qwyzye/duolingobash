from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import get_user, get_fragment_by_level, save_translation, add_points
from handlers.ai import check_user_translation
from handlers.locales import get_text

router = Router()

class PracticeState(StatesGroup):
    waiting_for_text = State()
    waiting_for_dispute = State()

LANG_NAMES = {"ru": {"ru": "русский", "en": "Russian", "kk": "орыс"}, 
              "en": {"ru": "английский", "en": "English", "kk": "ағылшын"}, 
              "kk": {"ru": "қазақ", "en": "Kazakh", "kk": "қазақ"}}

def get_next_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_next", lang), callback_data="menu_practice")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
    ])

@router.callback_query(F.data == "menu_practice")
async def start_practice(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    ui_lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    target_lang = LANG_NAMES[ui_lang][ui_lang]
    
    fragment = get_fragment_by_level(user['level'])
    if not fragment:
        await callback.message.edit_text(get_text("daily_empty", ui_lang))
        return
        
    await state.update_data(frag_id=fragment['fragment_id'], text_ba=fragment['text_ba'], target_lang=target_lang, ui_lang=ui_lang)
    await state.set_state(PracticeState.waiting_for_text)
    
    text = get_text("practice_title", ui_lang, lang=target_lang, text=fragment['text_ba'])
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text("btn_back", ui_lang), callback_data="menu_main")]])
    )

@router.message(PracticeState.waiting_for_text)
async def process_practice_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    text_ba = data.get('text_ba')
    target_lang = data.get('target_lang')
    ui_lang = data.get('ui_lang')
    user_answer = message.text
    
    await state.update_data(user_answer=user_answer)
    msg = await message.answer(get_text("checking", ui_lang))
    
    ai_result = await check_user_translation(text_ba, user_answer, target_lang)
    
    if ai_result.get('is_correct'):
        new_level = add_points(message.from_user.id, 20)
        await msg.edit_text(
            get_text("correct", ui_lang, explanation=ai_result.get('explanation')),
            reply_markup=get_next_kb(ui_lang)
        )
        await state.clear()
    else:
        await state.set_state(PracticeState.waiting_for_dispute)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_dispute", ui_lang), callback_data="practice_dispute")],
            [InlineKeyboardButton(text=get_text("btn_back", ui_lang), callback_data="menu_main")]
        ])
        await msg.edit_text(
            get_text("error_found", ui_lang, correct=ai_result.get('correct_translation'), explanation=ai_result.get('explanation')),
            reply_markup=kb
        )

@router.callback_query(F.data == "practice_dispute", PracticeState.waiting_for_dispute)
async def handle_practice_dispute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ui_lang = data.get('ui_lang', 'ru')
    
    save_translation(data.get('frag_id'), callback.from_user.id, data.get('user_answer'), status='expert_review')
    add_points(callback.from_user.id, 10)
    
    await callback.message.edit_text(
        get_text("dispute_saved", ui_lang),
        reply_markup=get_next_kb(ui_lang)
    )
    await state.clear()
    await callback.answer()