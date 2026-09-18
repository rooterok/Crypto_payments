"""
Общая логика выдачи доступа — оплата (process_paid_invoice) и бесплатный
пробный период (grant_trial) делают одно и то же (продлить + выдать ссылку +
уведомить), поэтому создание инвайт-ссылки вынесено в общий хелпер.
process_paid_invoice защищена от повторной обработки одного и того же
инвойса (db.mark_invoice_paid) — вызывается и из вебхука, и из
подстраховочного поллера.
"""
import datetime as dt
import logging

from aiogram import Bot

import db
from config import CHANNEL_ID, CHANNEL_TITLE, SUBSCRIPTION_DAYS

log = logging.getLogger(__name__)


async def _issue_invite_link(bot: Bot, telegram_id: int, name_prefix: str) -> str | None:
    try:
        link = await bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=48),
            name=f"{name_prefix}_{telegram_id}",
        )
        return link.invite_link
    except Exception:
        log.exception("Не удалось создать инвайт-ссылку для %s", telegram_id)
        return None


async def process_paid_invoice(bot: Bot, invoice_id: int, telegram_id: int) -> None:
    first_time = await db.mark_invoice_paid(invoice_id)
    if not first_time:
        return  # уже обработали этот инвойс раньше — ничего не делаем

    new_until = await db.extend_subscription(telegram_id, SUBSCRIPTION_DAYS)
    await db.set_trial_flag(telegram_id, False)  # реальная оплата — больше не триал
    pretty_date = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")

    invite_link = await _issue_invite_link(bot, telegram_id, "user")

    text = f"✅ Оплата получена! Подписка активна до {pretty_date}.\n\n"
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


async def grant_trial(bot: Bot, telegram_id: int, days: int) -> str:
    """Выдаёт бесплатный пробный доступ на `days` дней. Возвращает ISO-дату
    окончания триала (extend_subscription сама разберётся с базой — если у
    человека уже была активная подписка, триал добавится поверх неё)."""
    new_until = await db.extend_subscription(telegram_id, days)
    await db.set_trial_flag(telegram_id, True)
    pretty_date = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")

    invite_link = await _issue_invite_link(bot, telegram_id, "trial")

    text = f"🎁 Тебе открыли пробный доступ до {pretty_date}.\n\n"
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
        log.exception("Не удалось отправить сообщение о пробном доступе %s", telegram_id)

    return new_until
