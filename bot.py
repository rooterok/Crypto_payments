"""
Точка входа. Поднимает:
  1. aiogram-бота на long polling (сам бот, команды пользователей/админа)
  2. aiohttp-сервер на PORT — принимает вебхук invoice_paid от @CryptoBot
  3. APScheduler — ежедневные напоминания/кик за просрочку + подстраховочный
     опрос статусов инвойсов на случай, если вебхук не дошёл
"""
import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiohttp import web
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import admin
import db
import handlers
from config import BOT_TOKEN, INVOICE_POLL_INTERVAL, PORT, WEBHOOK_PATH
from cryptopay import verify_webhook_signature
from payment_logic import process_paid_invoice
from scheduler_jobs import kick_expired, poll_pending_invoices, remind_expiring

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")


async def handle_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    signature = request.headers.get("crypto-pay-api-signature", "")
    if not verify_webhook_signature(body, signature):
        log.warning("Webhook: неверная подпись")
        return web.Response(status=403)

    import json

    data = json.loads(body)
    if data.get("update_type") == "invoice_paid":
        invoice = data["payload"]
        telegram_id = int(invoice.get("payload") or 0)
        if telegram_id:
            bot: Bot = request.app["bot"]
            await process_paid_invoice(bot, invoice["invoice_id"], telegram_id)
        else:
            log.warning("Webhook: в инвойсе %s нет payload с telegram_id", invoice.get("invoice_id"))

    return web.Response(status=200)


async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def run_web_app(bot: Bot) -> None:
    app = web.Application()
    app["bot"] = bot
    app.router.add_post(WEBHOOK_PATH, handle_webhook)
    app.router.add_get("/", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log.info("Webhook-сервер слушает порт %s, путь %s", PORT, WEBHOOK_PATH)


async def main() -> None:
    await db.init_db()

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(handlers.router)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(remind_expiring, "cron", hour=9, args=[bot], id="remind_expiring")
    scheduler.add_job(kick_expired, "cron", hour=10, args=[bot], id="kick_expired")
    scheduler.add_job(
        poll_pending_invoices,
        "interval",
        seconds=INVOICE_POLL_INTERVAL,
        args=[bot],
        id="poll_pending_invoices",
    )
    scheduler.start()

    await run_web_app(bot)
    log.info("Бот запущен, начинаю polling")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
