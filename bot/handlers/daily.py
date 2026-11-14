import html
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from handlers.db import (
    get_or_create_user, check_daily_limit, increment_daily_count,
    get_fragment_by_level, upsert_translation, award_points,
    get_best_translation, is_fragment_parsed,
)
from handlers.ai import get_daily_translation
from handlers.locales import get_text
from handlers.tts import synthesize

router = Router()

LANG_NAMES = {
    "ru": {"ru": "русский", "en": "Russian", "kk": "орыс"},
    "en": {"ru": "английский", "en": "English", "kk": "ағылшын"},
    "kk": {"ru": "қазақ", "en": "Kazakh", "kk": "қазақ"},
}


class DailyState(StatesGroup):
    waiting_for_correction = State()


def _lang(user):
    return user["lang_pair"].split("-")[-1] if user and user.get("lang_pair") else "ru"


def _next_kb(lang):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_next", lang), callback_data="menu_daily")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")],
    ])


@router.callback_query(F.data == "menu_daily")
async def start_daily(callback: CallbackQuery, state: FSMContext):
    user = get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.first_name)
    if not user:
        await callback.answer(get_text("error_generic", "ru"), show_alert=True)
        return
    lang = _lang(user)
    target = LANG_NAMES.get(lang, LANG_NAMES["ru"])[lang]

    if not check_daily_limit(callback.from_user.id):
        await callback.message.edit_text(
            get_text("daily_limit", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
            ]),
        )
        await callback.answer()
        return

    fragment = get_fragment_by_level(user["level"])
    if not fragment:
        await callback.message.edit_text(
            get_text("daily_empty", lang),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
            ]),
        )
        await callback.answer()
        return

    msg = await callback.message.edit_text(get_text("processing", lang))
    await callback.answer()

    lang_pair = user["lang_pair"] or f"ba-{lang}"
    parsed = is_fragment_parsed(fragment["fragment_id"])
    existing = get_best_translation(fragment["fragment_id"], lang_pair)

    if existing and existing.get("status") == "confirmed":
        ai_translation = existing["translation"]
        is_messed = False
    else:
        ai = await get_daily_translation(fragment["text_ba"], target)
        if not ai:
            await msg.edit_text(
                get_text("ai_error", lang),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")]
                ]),
            )
            return
        is_messed = bool(ai.get("is_messed_up"))
        ai_translation = ai.get("translation", "")

    await state.update_data(
        fragment_id=fragment["fragment_id"],
        text_ba=fragment["text_ba"],
        source=fragment.get("source") or "",
        lang_pair=lang_pair,
        ai_translation=ai_translation,
        is_messed_up=is_messed,
        is_parsed=parsed,
        ui_lang=lang,
    )

    kb_rows = []
    if not is_messed and not parsed:
        kb_rows.append([InlineKeyboardButton(text=get_text("btn_confirm", lang), callback_data="daily_confirm")])
    kb_rows.append([InlineKeyboardButton(text=get_text("btn_correct", lang), callback_data="daily_correct")])
    kb_rows.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="menu_main")])

    badge = f"\n{get_text('parsed_badge', lang)}" if parsed else ""
    text = (
        f"{get_text('task_level', lang, level=user['level'])}\n\n"
        f"<b>{get_text('original', lang)}</b> <i>{html.escape(fragment['text_ba'])}</i>\n"
        f"<b>{get_text('ai_translation', lang, lang=target)}</b> {html.escape(ai_translation)}\n\n"
        f"<i>{get_text('source', lang)} {html.escape(fragment.get('source') or '')}</i>"
        f"{badge}"
    )
    await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows), parse_mode="HTML")
    increment_daily_count(callback.from_user.id)

    voice = synthesize(fragment["text_ba"])
    if voice:
        try:
            await callback.message.answer_voice(BufferedInputFile(voice, filename="voice.ogg"))
        except Exception:
            pass


@router.callback_query(F.data == "daily_confirm")
async def handle_daily_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("ui_lang", "ru")

    if not data.get("fragment_id"):
        await callback.answer(get_text("session_expired", lang), show_alert=True)
        return
    if data.get("is_parsed"):
        await callback.answer(get_text("parsed_locked", lang), show_alert=True)
        return
    if data.get("is_messed_up"):
        await callback.answer(get_text("wrong_translation_warn", lang), show_alert=True)
        return

    trans_id, confirmed, status, already = upsert_translation(
        fragment_id=data["fragment_id"],
        lang_pair=data["lang_pair"],
        text_ba=data["text_ba"],
        source=data["source"],
        translation=data["ai_translation"],
        user_id=callback.from_user.id,
        vote_type="confirm",
    )
    if status == "parsed_locked":
        await callback.answer(get_text("parsed_locked", lang), show_alert=True)
        return

    if already:
        await callback.answer(get_text("already_voted", lang), show_alert=True)
    else:
        new_level = award_points(
            callback.from_user.id, "daily_confirm",
            f"{data['fragment_id']}_{data['lang_pair']}", 15,
        )
        msg_text = get_text("confirmed", lang)
        if new_level > 1:
            msg_text += f"\n\n{get_text('level_up', lang, level=new_level)}"
        await callback.message.edit_text(msg_text, reply_markup=_next_kb(lang))
        await callback.answer()

    await state.update_data(fragment_id=None)


@router.callback_query(F.data == "daily_correct")
async def handle_daily_correct(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("ui_lang", "ru")
    if not data.get("fragment_id"):
        await callback.answer(get_text("session_expired", lang), show_alert=True)
        return
    if data.get("is_parsed"):
        await callback.answer(get_text("parsed_locked", lang), show_alert=True)
        return
    await state.set_state(DailyState.waiting_for_correction)
    await callback.message.edit_text(get_text("write_correction", lang))
    await callback.answer()


@router.message(DailyState.waiting_for_correction)
async def save_daily_correction(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("ui_lang", "ru")
    if not data.get("fragment_id"):
        await message.answer(get_text("session_expired", lang))
        await state.clear()
        return

    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 500:
        await message.answer(get_text("correction_too_short", lang))
        return

    trans_id, confirmed, status, already = upsert_translation(
        fragment_id=data["fragment_id"],
        lang_pair=data["lang_pair"],
        text_ba=data["text_ba"],
        source=data["source"],
        translation=text,
        user_id=message.from_user.id,
        vote_type="correct",
    )
    if status == "parsed_locked":
        await message.answer(get_text("parsed_locked", lang))
        await state.clear()
        return

    new_level = 1
    if not already:
        new_level = award_points(
            message.from_user.id, "daily_correct",
            f"{data['fragment_id']}_{data['lang_pair']}", 25,
        )
        msg = get_text("correction_saved", lang)
        if new_level > 1:
            msg += f"\n\n{get_text('level_up', lang, level=new_level)}"
    else:
        msg = get_text("already_voted", lang)

    await message.answer(msg, reply_markup=_next_kb(lang))
    await state.clear()