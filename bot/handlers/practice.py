import html
import uuid
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import (
    get_or_create_user, get_fragment_by_level, upsert_translation,
    save_to_expert_review, award_points, count_events_today, is_fragment_parsed,
)
from handlers.ai import check_user_translation
from handlers.locales import get_text
from config import PRACTICE_DAILY_LIMIT, DISPUTE_DAILY_LIMIT

router = Router()

LANG_NAMES = {
    "ru": {"ru": "русский", "en": "Russian", "kk": "орыс"},
    "en": {"ru": "английский", "en": "English", "kk": "ағылшын"},
    "kk": {"ru": "қазақ", "en": "Kazakh", "kk": "қазақ"},
}


class PracticeState(StatesGroup):
    waiting_for_text = State()
    waiting_for_dispute = State()


def _lang(user):
    return user["lang_pair"].split("-")[-1] if user and user.get("lang_pair") else "ru"


def _next_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_next", lang), callback_data="menu_practice")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")],
    ])


@router.callback_query(F.data == "menu_practice")
async def start_practice(callback: CallbackQuery, state: FSMContext):
    user = get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    if not user:
        await callback.answer(get_text("error_generic", "ru"), show_alert=True)
        return
    lang = _lang(user)

    if count_events_today(callback.from_user.id, ["practice_start"]) >= PRACTICE_DAILY_LIMIT:
        await callback.message.edit_text(
            get_text("practice_limit", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
            ]),
        )
        await callback.answer()
        return

    fragment = get_fragment_by_level(user["level"])
    if not fragment:
        await callback.message.edit_text(get_text("daily_empty", lang))
        await callback.answer()
        return

    target = LANG_NAMES.get(lang, LANG_NAMES["ru"])[lang]
    session_id = str(uuid.uuid4())
    award_points(callback.from_user.id, "practice_start", session_id, 0)

    await state.update_data(
        fragment_id=fragment["fragment_id"],
        text_ba=fragment["text_ba"],
        source=fragment.get("source") or "",
        lang_pair=user["lang_pair"] or f"ba-{lang}",
        target_lang=target,
        ui_lang=lang,
        session_id=session_id,
    )
    await state.set_state(PracticeState.waiting_for_text)

    text = get_text("practice_title", lang, lang=target, text=html.escape(fragment["text_ba"]))
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PracticeState.waiting_for_text)
async def process_practice_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("ui_lang", "ru")
    answer = (message.text or "").strip()
    if len(answer) < 2 or len(answer) > 500:
        await message.answer(get_text("correction_too_short", lang))
        return

    msg = await message.answer(get_text("checking", lang))

    ai = await check_user_translation(data["text_ba"], answer, data["target_lang"])
    if not ai:
        await msg.edit_text(
            get_text("ai_error", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
            ]),
        )
        await state.clear()
        return

    await state.update_data(user_answer=answer)

    if ai.get("is_correct"):
        upsert_translation(
            fragment_id=data["fragment_id"],
            lang_pair=data["lang_pair"],
            text_ba=data["text_ba"],
            source=data["source"],
            translation=answer,
            user_id=message.from_user.id,
            vote_type="confirm",
        )
        award_points(message.from_user.id, "practice_correct", data["session_id"], 20)
        await msg.edit_text(
            get_text("correct", lang, explanation=html.escape(ai.get("explanation") or "")),
            reply_markup=_next_kb(lang),
            parse_mode="HTML",
        )
        await state.clear()
    else:
        await state.set_state(PracticeState.waiting_for_dispute)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_dispute", lang), callback_data="practice_dispute")],
            [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")],
        ])
        await msg.edit_text(
            get_text("error_found", lang,
                     correct=html.escape(ai.get("correct_translation") or ""),
                     explanation=html.escape(ai.get("explanation") or "")),
            reply_markup=kb,
            parse_mode="HTML",
        )


@router.callback_query(F.data == "practice_dispute", PracticeState.waiting_for_dispute)
async def handle_practice_dispute(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("ui_lang", "ru")

    if count_events_today(callback.from_user.id, ["practice_dispute"]) >= DISPUTE_DAILY_LIMIT:
        await callback.answer(get_text("dispute_limit", lang), show_alert=True)
        return

    save_to_expert_review(
        fragment_id=data["fragment_id"],
        user_id=callback.from_user.id,
        translation=data.get("user_answer", ""),
        lang_pair=data["lang_pair"],
        text_ba=data["text_ba"],
        source=data["source"],
    )
    award_points(callback.from_user.id, "practice_dispute", data["session_id"], 5)

    await callback.message.edit_text(
        get_text("dispute_saved", lang),
        reply_markup=_next_kb(lang),
    )
    await state.clear()
    await callback.answer()