"""
Пользовательские хендлеры: /start, /status, /pay.
"""
import datetime as dt
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import db
from config import BOT_USERNAME, CHANNEL_TITLE, SUBSCRIPTION_PRICE_USD
from cryptopay import create_invoice

log = logging.getLogger(__name__)
router = Router()


def _pay_keyboard(pay_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="💳 Оплатить в крипте", url=pay_url)]]
    )


async def _send_invoice(message: Message, telegram_id: int) -> None:
    paid_btn_url = f"https://t.me/{BOT_USERNAME}" if BOT_USERNAME else None
    invoice = await create_invoice(
        amount_usd=SUBSCRIPTION_PRICE_USD,
        telegram_id=telegram_id,
        description=f"Подписка на {CHANNEL_TITLE} — 1 месяц",
        paid_btn_url=paid_btn_url,
    )
    await db.create_invoice_record(
        invoice_id=invoice["invoice_id"],
        telegram_id=telegram_id,
        amount=SUBSCRIPTION_PRICE_USD,
    )
    text = (
        f"Подписка на {CHANNEL_TITLE}: ${SUBSCRIPTION_PRICE_USD}/мес.\n"
        "Оплата в крипте (USDT/TON/BTC — на выбор при оплате). "
        "После оплаты доступ откроется автоматически."
    )
    await message.answer(text, reply_markup=_pay_keyboard(invoice["bot_invoice_url"]))


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user = await db.get_or_create_user(message.from_user.id, message.from_user.username)

    if user["status"] == "active" and user["paid_until"]:
        until = dt.datetime.fromisoformat(user["paid_until"])
        if until > dt.datetime.now(dt.timezone.utc):
            pretty = until.strftime("%d.%m.%Y")
            await message.answer(
                f"✅ Подписка активна до {pretty}.\n"
                f"Можно продлить заранее — команда /pay."
            )
            return

    await message.answer(
        f"Привет! Здесь можно оформить доступ к {CHANNEL_TITLE} "
        f"по подписке ${SUBSCRIPTION_PRICE_USD}/мес, оплата криптой."
    )
    await _send_invoice(message, message.from_user.id)


@router.message(Command("pay"))
async def cmd_pay(message: Message) -> None:
    await db.get_or_create_user(message.from_user.id, message.from_user.username)
    await _send_invoice(message, message.from_user.id)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    user = await db.get_user(message.from_user.id)
    if not user or not user["paid_until"]:
        await message.answer("Подписки пока нет. Оформить — /pay")
        return
    until = dt.datetime.fromisoformat(user["paid_until"])
    is_active = until > dt.datetime.now(dt.timezone.utc) and user["status"] == "active"
    state = "активна" if is_active else "истекла"
    await message.answer(
        f"Статус подписки: {state}.\nДействует до: {until.strftime('%d.%m.%Y')}"
    )
