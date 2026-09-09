"""
Периодические задачи:
  - remind_expiring: раз в день напоминает тем, у кого подписка скоро кончается,
    и сразу выставляет инвойс на продление
  - kick_expired: раз в день выгоняет из канала тех, кто не продлил после грейс-периода
  - poll_pending_invoices: подстраховка на случай, если вебхук от CryptoBot не дошёл —
    сам спрашивает API о статусе недавних инвойсов
"""
import datetime as dt
import logging

from aiogram import Bot

import db
from config import (
    BOT_USERNAME,
    CHANNEL_ID,
    CHANNEL_TITLE,
    GRACE_PERIOD_DAYS,
    REMINDER_DAYS_BEFORE,
    SUBSCRIPTION_PRICE_USD,
)
from cryptopay import create_invoice, get_invoices
from payment_logic import process_paid_invoice

log = logging.getLogger(__name__)


async def remind_expiring(bot: Bot) -> None:
    today_str = dt.datetime.now(dt.timezone.utc).date().isoformat()
    users = await db.users_needing_reminder(REMINDER_DAYS_BEFORE)
    for user in users:
        telegram_id = user["telegram_id"]
        try:
            paid_btn_url = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else None
            invoice = await create_invoice(
                amount_usd=SUBSCRIPTION_PRICE_USD,
                telegram_id=telegram_id,
                description=f"Продление подписки на {CHANNEL_TITLE} — 1 месяц",
                paid_btn_url=paid_btn_url,
            )
            await db.create_invoice_record(
                invoice_id=invoice["invoice_id"],
                telegram_id=telegram_id,
                amount=SUBSCRIPTION_PRICE_USD,
            )
            until = dt.datetime.fromisoformat(user["paid_until"]).strftime("%d.%m.%Y")
            await bot.send_message(
                telegram_id,
                f"⏳ Подписка на {CHANNEL_TITLE} заканчивается {until}.\n"
                f"Продлить на месяц (${SUBSCRIPTION_PRICE_USD}):",
                reply_markup=_pay_kb(invoice["bot_invoice_url"]),
            )
            await db.set_last_reminder(telegram_id, today_str)
        except Exception:
            log.exception("Не удалось отправить напоминание %s", telegram_id)


async def kick_expired(bot: Bot) -> None:
    users = await db.users_to_kick(GRACE_PERIOD_DAYS)
    for user in users:
        telegram_id = user["telegram_id"]
        try:
            await bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id)
            await bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=telegram_id, only_if_banned=True)
        except Exception:
            log.exception("Не удалось убрать %s из канала", telegram_id)
        await db.set_status(telegram_id, "expired")
        try:
            await bot.send_message(
                telegram_id,
                f"Доступ к {CHANNEL_TITLE} приостановлен — подписка не была продлена.\n"
                "Оформить заново: /pay",
            )
        except Exception:
            pass


async def poll_pending_invoices(bot: Bot) -> None:
    pending = await db.get_pending_invoices()
    if not pending:
        return
    invoice_ids = [p["invoice_id"] for p in pending]
    try:
        remote = await get_invoices(invoice_ids)
    except Exception:
        log.exception("Не удалось опросить getInvoices")
        return
    for inv in remote:
        if inv.get("status") == "paid":
            telegram_id = int(inv.get("payload") or 0)
            if not telegram_id:
                local = await db.get_invoice(inv["invoice_id"])
                telegram_id = local["telegram_id"] if local else 0
            if telegram_id:
                await process_paid_invoice(bot, inv["invoice_id"], telegram_id)


def _pay_kb(pay_url: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить в крипте", url=pay_url)]]
    )
