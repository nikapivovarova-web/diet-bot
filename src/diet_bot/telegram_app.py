from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

from .builder import build_one_day_plan
from .domain import UserProfile
from .presentation import format_meal_card, format_plan_messages
from .questionnaire import QuestionnaireSession, start_session
from .validation import validate_plan


SESSION_BY_CHAT_ID: dict[int, QuestionnaireSession] = {}
PROFILE_BY_CHAT_ID: dict[int, UserProfile] = {}
PLAN_COUNT_BY_CHAT_ID: dict[int, int] = {}
router = Router()

START_PLAN_TEXT = "🥗 Составить план"
REPEAT_PLAN_TEXT = "🔄 Составить еще один рацион"
NEW_PROFILE_TEXT = "📝 Новая анкета"


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет! 🥗 Я помогу собрать рацион на 1 день по вашим данным.\n\n"
        "Важно: бот не заменяет врача и не назначает лечебные диеты 🩺",
        reply_markup=_start_keyboard(),
    )


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    await _start_questionnaire(message)


@router.message(Command("cancel"))
async def cancel(message: Message) -> None:
    SESSION_BY_CHAT_ID.pop(message.chat.id, None)
    await message.answer("Анкета сброшена ✅", reply_markup=_start_keyboard())


@router.message()
async def handle_answer(message: Message) -> None:
    chat_id = message.chat.id
    text = (message.text or "").strip()
    if text in {START_PLAN_TEXT, NEW_PROFILE_TEXT}:
        await _start_questionnaire(message)
        return
    if text == REPEAT_PLAN_TEXT:
        await _repeat_plan(message)
        return

    session = SESSION_BY_CHAT_ID.get(chat_id)
    if session is None:
        await message.answer("Нажмите кнопку, чтобы составить рацион 👇", reply_markup=_start_keyboard())
        return

    next_session, error = session.receive(text)
    if error:
        await message.answer(error)
        await message.answer(
            session.current_question.prompt,
            reply_markup=_question_keyboard(session.current_question),
        )
        return

    SESSION_BY_CHAT_ID[chat_id] = next_session
    if not next_session.is_complete:
        await message.answer(
            next_session.current_question.prompt,
            reply_markup=_question_keyboard(next_session.current_question),
        )
        return

    profile = next_session.build_profile()
    PROFILE_BY_CHAT_ID[chat_id] = profile
    PLAN_COUNT_BY_CHAT_ID[chat_id] = 0
    SESSION_BY_CHAT_ID.pop(chat_id, None)
    await _send_plan(message, profile)


def create_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot() -> None:
    token = os.getenv("DIET_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Set DIET_BOT_TOKEN or TELEGRAM_BOT_TOKEN.")
    bot = Bot(token)
    dispatcher = create_dispatcher()
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_bot())


def _telegram_chunks(text: str, limit: int = 3900) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        chunks.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()
    if remaining:
        chunks.append(remaining)
    return chunks


async def _start_questionnaire(message: Message) -> None:
    session = start_session()
    SESSION_BY_CHAT_ID[message.chat.id] = session
    await message.answer(
        session.current_question.prompt,
        reply_markup=_question_keyboard(session.current_question),
    )


async def _repeat_plan(message: Message) -> None:
    profile = PROFILE_BY_CHAT_ID.get(message.chat.id)
    if profile is None:
        await _start_questionnaire(message)
        return
    await _send_plan(message, profile)


async def _send_plan(message: Message, profile: UserProfile) -> None:
    chat_id = message.chat.id
    seed = PLAN_COUNT_BY_CHAT_ID.get(chat_id, 0)
    PLAN_COUNT_BY_CHAT_ID[chat_id] = seed + 1
    await message.answer("Считаю рацион и проверяю ограничения... 🧮", reply_markup=ReplyKeyboardRemove())
    plan_result = build_one_day_plan(profile, variety_seed=seed)
    validation = validate_plan(plan_result)
    messages = format_plan_messages(plan_result, validation)
    if not plan_result.safety.can_generate_plan:
        await _send_text_chunks(message, messages[0], _after_plan_keyboard())
        return

    await _send_text_chunks(message, messages[0])
    for meal in plan_result.meals:
        await _send_meal_card(message, meal)
    for index, response in enumerate(messages[2:]):
        markup = _after_plan_keyboard() if index == len(messages[2:]) - 1 else None
        await _send_text_chunks(message, response, markup)


def _start_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=START_PLAN_TEXT)]],
        resize_keyboard=True,
    )


def _after_plan_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=REPEAT_PLAN_TEXT)],
            [KeyboardButton(text=NEW_PROFILE_TEXT)],
        ],
        resize_keyboard=True,
    )


def _question_keyboard(question) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    if not question or not question.options:
        return ReplyKeyboardRemove()
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=option)] for option in question.options],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def _send_text_chunks(
    message: Message,
    text: str,
    reply_markup: ReplyKeyboardMarkup | ReplyKeyboardRemove | None = None,
) -> None:
    chunks = _telegram_chunks(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        await message.answer(chunk, reply_markup=markup)


async def _send_meal_card(message: Message, meal) -> None:
    caption = format_meal_card(meal)
    if meal.image_url:
        try:
            await message.answer_photo(photo=meal.image_url, caption=caption[:1024])
            if len(caption) > 1024:
                await _send_text_chunks(message, caption[1024:])
            return
        except TelegramAPIError:
            pass
    await _send_text_chunks(message, caption)


if __name__ == "__main__":
    main()
