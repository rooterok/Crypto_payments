"""
Общая логика обработки успешной оплаты — вызывается и из вебхука,
и из подстраховочного поллера, поэтому вынесена отдельно и защищена
от повторной обработки одного и того же инвойса (db.mark_invoice_paid).
"""
import datetime as dt
import logging

from aiogram import Bot

import db
from config import CHANNEL_ID, CHANNEL_TITLE, SUBSCRIPTION_DAYS

log = logging.getLogger(__name__)


async def process_paid_invoice(bot: Bot, invoice_id: int, telegram_id: int) -> None:
    first_time = await db.mark_invoice_paid(invoice_id)
    if not first_time:
        return  # уже обработали этот инвойс раньше — ничего не делаем

    new_until = await db.extend_subscription(telegram_id, SUBSCRIPTION_DAYS)
    pretty_date = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")

    invite_link = None
    try:
        link = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=48),
            name=f"user_{telegram_id}",
        )
        invite_link = link.invite_link
    except Exception:
        log.exception("Не удалось создать инвайт-ссылку для %s", telegram_id)

    text = (
        f"✅ Оплата получена! Подписка активна до {pretty_date}.\n\n"
    )
    if invite_link:
        text += f"Ссылка на {CHANNEL_TITLE} (одноразовая, для тебя): {invite_link}"
    else:
        text += (
            f"Не получилось автоматически выдать ссылку на {CHANNEL_TITLE} — "
            "напиши в поддержку, тебя добавят вручную."
        )

    try:
        await bot.send_message(telegram_id, text)
    except Exception:
        log.exception("Не удалось отправить сообщение пользователю %s", telegram_id)
