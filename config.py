"""
Конфигурация бота — все настройки приходят из переменных окружения.
На Railway они задаются во вкладке Variables сервиса.
"""
import os


def _int_list(raw: str) -> list[int]:
    return [int(x.strip()) for x in raw.split(",") if x.strip()]


# --- обязательные ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
CRYPTO_PAY_TOKEN = os.environ["CRYPTO_PAY_TOKEN"]
CHANNEL_ID = int(os.environ["CHANNEL_ID"])  # например -1001234567890
ADMIN_IDS = _int_list(os.environ.get("ADMIN_IDS", ""))

# --- опциональные, есть значения по умолчанию ---
CRYPTO_PAY_API_URL = os.environ.get(
    "CRYPTO_PAY_API_URL", "https://pay.crypt.bot/api"
)  # для теста: https://testnet-pay.crypt.bot/api (и токен из @CryptoTestnetBot)

SUBSCRIPTION_PRICE_USD = os.environ.get("SUBSCRIPTION_PRICE_USD", "25")
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))
GRACE_PERIOD_DAYS = int(os.environ.get("GRACE_PERIOD_DAYS", "2"))
REMINDER_DAYS_BEFORE = int(os.environ.get("REMINDER_DAYS_BEFORE", "3"))
ACCEPTED_ASSETS = os.environ.get("ACCEPTED_ASSETS", "USDT,TON,BTC")
INVOICE_EXPIRES_IN = int(os.environ.get("INVOICE_EXPIRES_IN", str(24 * 3600)))

BOT_USERNAME = os.environ.get("BOT_USERNAME", "")  # без @, для кнопки "открыть бота"
CHANNEL_TITLE = os.environ.get("CHANNEL_TITLE", "приватный чат")

# Путь к файлу базы — на Railway должен указывать внутрь примонтированного volume,
# иначе данные исчезнут при каждом новом деплое.
DB_PATH = os.environ.get("DB_PATH", "/data/subscriptions.db")

# Порт для вебхука CryptoBot (Railway сам подставит переменную PORT)
PORT = int(os.environ.get("PORT", "8080"))
WEBHOOK_PATH = "/cryptobot-webhook"

# Как часто подстраховочно опрашивать статус выставленных инвойсов (сек)
INVOICE_POLL_INTERVAL = int(os.environ.get("INVOICE_POLL_INTERVAL", "300"))
