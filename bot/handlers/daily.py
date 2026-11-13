from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import get_user, check_daily_limit, increment_daily_count, get_fragment_by_level, save_translation, confirm_translation, add_points
from handlers.ai import get_daily_translation
from handlers.locales import get_text

router = Router()

class DailyState(StatesGroup):
    waiting_for_correction = State()

LANG_NAMES = {"ru": {"ru": "русский", "en": "Russian", "kk": "орыс"}, 
              "en": {"ru": "английский", "en": "English", "kk": "ағылшын"}, 
              "kk": {"ru": "қазақ", "en": "Kazakh", "kk": "қазақ"}}

def get_next_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_next", lang), callback_data="menu_daily")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
    ])

@router.callback_query(F.data == "menu_daily")
async def start_daily(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    ui_lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    target_lang = LANG_NAMES[ui_lang][ui_lang] # Переводим на тот же язык, что и интерфейс

    if not check_daily_limit(user_id):
        await callback.message.edit_text(
            get_text("daily_limit", ui_lang), 
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text("btn_back", ui_lang), callback_data="menu_main")]])
        )
        return

    fragment = get_fragment_by_level(user['level'])
    if not fragment:
        await callback.message.edit_text(get_text("daily_empty", ui_lang), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text("btn_back", ui_lang), callback_data="menu_main")]]))
        return

    msg = await callback.message.edit_text(get_text("processing", ui_lang))
    
    ai_result = await get_daily_translation(fragment['text_ba'], target_lang)
    if not ai_result:
        await msg.edit_text(get_text("ai_error", ui_lang))
        return

    trans_id = save_translation(fragment['fragment_id'], user_id, ai_result['translation'], status='pending')
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_confirm", ui_lang), callback_data=f"daily_confirm_{trans_id}")],
        [InlineKeyboardButton(text=get_text("btn_correct", ui_lang), callback_data=f"daily_correct_{fragment['fragment_id']}")],
        [InlineKeyboardButton(text=get_text("btn_back", ui_lang), callback_data="menu_main")]
    ])
    
    text = (
        f"{get_text('task_level', ui_lang, level=user['level'])}\n\n"
        f"<b>{get_text('original', ui_lang)}</b> <i>{fragment['text_ba']}</i>\n"
        f"<b>{get_text('ai_translation', ui_lang, lang=target_lang)}</b> {ai_result['translation']}\n\n"
        f"<i>{get_text('source', ui_lang)} {fragment['source']}</i>"
    )
    await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
    increment_daily_count(user_id)

@router.callback_query(F.data.startswith("daily_confirm_"))
async def handle_daily_confirm(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    ui_lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    trans_id = int(callback.data.split("_")[2])
    confirm_translation(trans_id)
    new_level = add_points(callback.from_user.id, 15)
    
    text = get_text("confirmed", ui_lang)
    if new_level > 1:
        text += f"\n\n{get_text('level_up', ui_lang, level=new_level)}"
        
    await callback.message.edit_text(text, reply_markup=get_next_kb(ui_lang))
    await callback.answer()

@router.callback_query(F.data.startswith("daily_correct_"))
async def handle_daily_correct(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    ui_lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    frag_id = int(callback.data.split("_")[2])
    await state.update_data(frag_id=frag_id)
    await state.set_state(DailyState.waiting_for_correction)
    
    await callback.message.edit_text(get_text("write_correction", ui_lang))
    await callback.answer()

@router.message(DailyState.waiting_for_correction)
async def save_daily_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    frag_id = data.get('frag_id')
    
    user = get_user(message.from_user.id)
    ui_lang = user['lang_pair'].split("-")[1] if user.get('lang_pair') else "ru"
    
    save_translation(frag_id, message.from_user.id, message.text, status='expert_review')
    add_points(message.from_user.id, 25)
    
    await message.answer(
        get_text("correction_saved", ui_lang),
        reply_markup=get_next_kb(ui_lang)
    )
    await state.clear()