from __future__ import annotations

import asyncio
import os

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from .builder import build_one_day_plan
from .presentation import format_plan_response
from .questionnaire import QuestionnaireSession, start_session
from .validation import validate_plan


SESSION_BY_CHAT_ID: dict[int, QuestionnaireSession] = {}
router = Router()


@router.message(Command("start"))
async def start(message: Message) -> None:
    await message.answer(
        "Привет. Я помогу собрать рацион на 1 день по вашим данным.\n\n"
        "Важно: бот не заменяет врача и не назначает лечебные диеты. "
        "Чтобы начать, отправьте /plan."
    )


@router.message(Command("plan"))
async def plan(message: Message) -> None:
    session = start_session()
    SESSION_BY_CHAT_ID[message.chat.id] = session
    await message.answer(session.current_question.prompt)


@router.message(Command("cancel"))
async def cancel(message: Message) -> None:
    SESSION_BY_CHAT_ID.pop(message.chat.id, None)
    await message.answer("Анкета сброшена. Чтобы начать заново, отправьте /plan.")


@router.message()
async def handle_answer(message: Message) -> None:
    chat_id = message.chat.id
    session = SESSION_BY_CHAT_ID.get(chat_id)
    if session is None:
        await message.answer("Чтобы составить рацион, отправьте /plan.")
        return

    next_session, error = session.receive(message.text or "")
    if error:
        await message.answer(error)
        await message.answer(session.current_question.prompt)
        return

    SESSION_BY_CHAT_ID[chat_id] = next_session
    if not next_session.is_complete:
        await message.answer(next_session.current_question.prompt)
        return

    await message.answer("Считаю рацион и проверяю ограничения...")
    profile = next_session.build_profile()
    plan_result = build_one_day_plan(profile)
    validation = validate_plan(plan_result)
    response = format_plan_response(plan_result, validation)
    SESSION_BY_CHAT_ID.pop(chat_id, None)
    for chunk in _telegram_chunks(response):
        await message.answer(chunk)


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


if __name__ == "__main__":
    main()
