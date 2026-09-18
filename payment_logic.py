"""
Общая логика выдачи доступа. Три пути приводят сюда: настоящая оплата
(process_paid_invoice), ручная выдача админом (/grant) и бесплатный пробный
период (/trial) — все три должны продлить подписку, выдать одноразовую
инвайт-ссылку и уведомить человека, поэтому это единая grant_access(),
отличающаяся только текстом сообщения и пометкой is_trial.
process_paid_invoice дополнительно защищена от повторной обработки одного
и того же инвойса (db.mark_invoice_paid) — вызывается и из вебхука, и из
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


async def grant_access(
    bot: Bot, telegram_id: int, days: int, is_trial: bool, intro: str
) -> str:
    """Продлевает подписку, выдаёт одноразовую инвайт-ссылку и уведомляет
    человека. `intro` — первая строка сообщения (разная для оплаты/триала/
    ручной выдачи), `is_trial` — как пометить пользователя в базе.
    Возвращает ISO-дату, до которой теперь открыт доступ."""
    new_until = await db.extend_subscription(telegram_id, days)
    await db.set_trial_flag(telegram_id, is_trial)
    pretty_date = dt.datetime.fromisoformat(new_until).strftime("%d.%m.%Y")

    invite_link = await _issue_invite_link(
        bot, telegram_id, "trial" if is_trial else "grant"
    )

    text = f"{intro} до {pretty_date}.\n\n"
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

    return new_until


async def process_paid_invoice(bot: Bot, invoice_id: int, telegram_id: int) -> None:
    first_time = await db.mark_invoice_paid(invoice_id)
    if not first_time:
        return  # уже обработали этот инвойс раньше — ничего не делаем
    await grant_access(
        bot,
        telegram_id,
        SUBSCRIPTION_DAYS,
        is_trial=False,
        intro="✅ Оплата получена! Подписка активна",
    )


async def grant_trial(bot: Bot, telegram_id: int, days: int) -> str:
    """Выдаёт бесплатный пробный доступ на `days` дней (сразу шлёт ссылку и
    уведомление, помечает пользователя как триального)."""
    return await grant_access(
        bot, telegram_id, days, is_trial=True, intro="🎁 Тебе открыли пробный доступ"
    )


async def grant_manual(bot: Bot, telegram_id: int, days: int) -> str:
    """/grant — ручная выдача/продление доступа админом (не триал). Тоже
    шлёт ссылку и уведомление — важно и для новых людей (иначе им нечем
    будет попасть в чат), и для уже действующих участников (у них просто
    появится трекинг подписки в базе)."""
    return await grant_access(
        bot, telegram_id, days, is_trial=False, intro="✅ Тебе открыли доступ"
    )
