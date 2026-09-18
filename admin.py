"""
Админские команды. Доступны только id из ADMIN_IDS.
Нужны в первую очередь чтобы:
  - вручную перенести уже существующих платных участников (/grant),
    прежде чем включать автоматический кик за просрочку;
  - выдать кому-то бесплатный пробный период (/trial);
  - смотреть, сколько активных подписок и выручка за месяц (/stats);
  - назначать индивидуальные условия конкретному человеку (/setprice);
  - смотреть всю базу подписчиков целиком (/list).
"""
import csv
import datetime as dt
import io

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

import db
from config import ADMIN_IDS, SUBSCRIPTION_PRICE_USD
from payment_logic import grant_manual, grant_trial

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
async def cmd_grant(message: Message, bot: Bot) -> None:
    """/grant <telegram_id> <дней> — выдать/продлить доступ вручную (не
    триал). Шлёт человеку уведомление и одноразовую инвайт-ссылку — подходит
    и для новых людей, и для переноса уже действующих участников (им ссылка
    не понадобится, но подписка появится в базе с трекингом даты)."""
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
    new_until = await grant_manual(bot, telegram_id, days)
    pretty = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")
    await message.answer(f"Готово. У {telegram_id} доступ до {pretty}, уведомление и ссылку отправил.")


@router.message(Command("trial"))
async def cmd_trial(message: Message, bot: Bot) -> None:
    """/trial <telegram_id> <дней> — выдать бесплатный пробный доступ:
    сразу открывает канал (шлёт человеку инвайт-ссылку) и помечает его как
    триального — когда пробный период подойдёт к концу, напоминание придёт
    с предложением оформить подписку, а не "продлить" (см. /grant для
    обычной ручной выдачи без этой пометки)."""
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /trial <telegram_id> <дней>")
        return
    try:
        telegram_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await message.answer("telegram_id и дней должны быть числами")
        return

    await db.get_or_create_user(telegram_id, None)
    new_until = await grant_trial(bot, telegram_id, days)
    pretty = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")
    await message.answer(f"Готово. У {telegram_id} пробный доступ до {pretty}, ссылку уже отправил.")


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
    price = user.get("custom_price_usd") or f"{SUBSCRIPTION_PRICE_USD} (стандартная)"
    trial_mark = " (триал)" if user.get("is_trial") else ""
    await message.answer(
        f"id: {user['telegram_id']}\n"
        f"username: @{user['username']}\n"
        f"статус: {user['status']}{trial_mark}\n"
        f"paid_until: {user['paid_until']}\n"
        f"цена: ${price}"
    )


@router.message(Command("setprice"))
async def cmd_setprice(message: Message) -> None:
    """/setprice <telegram_id> <сумма|default> — индивидуальная цена подписки
    для конкретного человека (например, скидка постоянному участнику).
    Применится к следующему выставленному счёту (при /pay или при
    автопродлении); на уже отправленный счёт не влияет.
    /setprice <telegram_id> default — вернуть стандартную цену."""
    if not _is_admin(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 3:
        await message.answer("Использование: /setprice <telegram_id> <сумма|default>")
        return
    try:
        telegram_id = int(parts[1])
    except ValueError:
        await message.answer("telegram_id должен быть числом")
        return

    await db.get_or_create_user(telegram_id, None)
    if parts[2].lower() == "default":
        await db.set_custom_price(telegram_id, None)
        await message.answer(f"У {telegram_id} снова стандартная цена (${SUBSCRIPTION_PRICE_USD}).")
        return
    try:
        price = str(float(parts[2].replace(",", ".")))
    except ValueError:
        await message.answer("Сумма должна быть числом, например 15 или 15.5")
        return
    await db.set_custom_price(telegram_id, price)
    await message.answer(f"Готово. У {telegram_id} теперь персональная цена: ${price}/мес.")


@router.message(Command("list", "export"))
async def cmd_list(message: Message) -> None:
    """/list — выгружает всю базу подписчиков CSV-файлом (открывается в Excel/
    Google Таблицах/Numbers): id, username, статус, до какой даты активна
    подписка, персональная цена, дата первого обращения к боту."""
    if not _is_admin(message.from_user.id):
        return
    users = await db.get_all_users()
    if not users:
        await message.answer("База пока пуста.")
        return

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["telegram_id", "username", "status", "is_trial", "paid_until", "custom_price_usd", "created_at"]
    )
    for u in users:
        writer.writerow(
            [
                u["telegram_id"],
                u["username"] or "",
                u["status"],
                "да" if u["is_trial"] else "",
                u["paid_until"] or "",
                u["custom_price_usd"] or "",
                u["created_at"],
            ]
        )
    data = buf.getvalue().encode("utf-8-sig")  # BOM, чтобы Excel сразу понял кодировку
    today = dt.date.today().isoformat()
    file = BufferedInputFile(data, filename=f"subscribers_{today}.csv")
    await message.answer_document(file, caption=f"Подписчиков в базе: {len(users)}")
