"""
Админские команды. Доступны только id из ADMIN_IDS.
Нужны в первую очередь чтобы:
  - вручную перенести уже существующих платных участников (/grant),
    прежде чем включать автоматический кик за просрочку;
  - смотреть, сколько активных подписок и выручка за месяц (/stats).
"""
import datetime as dt

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import db
from config import ADMIN_IDS

router = Router()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


@router.message(Command("stats"))
async def cmd_stats(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    s = await db.stats()
    await message.answer(
        "📊 Статистика\n"
        f"Активных подписок: {s['active']}\n"
        f"Просроченных: {s['expired']}\n"
        f"Всего пользователей бота: {s['total']}\n"
        f"Оплат в этом месяце: {s['paid_count_month']} на ${s['revenue_month']:.2f}"
    )


@router.message(Command("grant"))
async def cmd_grant(message: Message) -> None:
    """/grant <telegram_id> <дней> — выдать/продлить доступ вручную.
    Например, чтобы завести уже существующих 15 платных участников
    до того, как включать авто-кик за просрочку."""
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /grant <telegram_id> <дней>")
        return
    try:
        telegram_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.answer("telegram_id и дней должны быть числами")
        return

    await db.get_or_create_user(telegram_id, None)
    new_until = await db.extend_subscription(telegram_id, days)
    pretty = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")
    await message.answer(f"Готово. У {telegram_id} доступ до {pretty}.")


@router.message(Command("find"))
async def cmd_find(message: Message) -> None:
    """/find <telegram_id> — посмотреть статус конкретного пользователя."""
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /find <telegram_id>")
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("telegram_id должен быть числом")
        return
    user = await db.get_user(telegram_id)
    if not user:
        await message.answer("Такого пользователя нет в базе.")
        return
    await message.answer(
        f"id: {user['telegram_id']}\n"
        f"username: @{user['username']}\n"
        f"статус: {user['status']}\n"
        f"paid_until: {user['paid_until']}"
    )
