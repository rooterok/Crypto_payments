"""
Слой хранения данных. Простая SQLite-база (через aiosqlite) — для сотен
подписчиков этого более чем достаточно, и не нужно поднимать отдельный
сервис БД на Railway.
"""
import datetime as dt
from pathlib import Path

import aiosqlite

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id     INTEGER PRIMARY KEY,
    username        TEXT,
    paid_until      TEXT,       -- ISO datetime, NULL = ни разу не платил
    status          TEXT NOT NULL DEFAULT 'never',  -- never | active | expired
    last_reminder_at TEXT,      -- дата (YYYY-MM-DD) последнего отправленного напоминания
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id   INTEGER PRIMARY KEY,
    telegram_id  INTEGER NOT NULL,
    amount       TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'active',  -- active | paid | expired
    created_at   TEXT NOT NULL,
    paid_at      TEXT
);
"""


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


async def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()
        # Миграции для баз, созданных до появления этих колонок.
        cur = await db.execute("PRAGMA table_info(users)")
        columns = {row[1] for row in await cur.fetchall()}
        if "custom_price_usd" not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN custom_price_usd TEXT")
            await db.commit()
        if "is_trial" not in columns:
            await db.execute(
                "ALTER TABLE users ADD COLUMN is_trial INTEGER NOT NULL DEFAULT 0"
            )
            await db.commit()


async def get_or_create_user(telegram_id: int, username: str | None) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        if row:
            if username and row["username"] != username:
                await db.execute(
                    "UPDATE users SET username = ? WHERE telegram_id = ?",
                    (username, telegram_id),
                )
                await db.commit()
            return dict(row)

        await db.execute(
            "INSERT INTO users (telegram_id, username, paid_until, status, created_at) "
            "VALUES (?, ?, NULL, 'never', ?)",
            (telegram_id, username, now_iso()),
        )
        await db.commit()
        cur = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        return dict(await cur.fetchone())


async def get_user(telegram_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def extend_subscription(telegram_id: int, days: int) -> str:
    """Продлевает подписку от максимума(сейчас, текущий paid_until) и возвращает новую дату."""
    user = await get_user(telegram_id)
    now = dt.datetime.now(dt.timezone.utc)
    base = now
    if user and user["paid_until"]:
        current = dt.datetime.fromisoformat(user["paid_until"])
        if current > now:
            base = current
    new_until = base + dt.timedelta(days=days)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET paid_until = ?, status = 'active' WHERE telegram_id = ?",
            (new_until.isoformat(), telegram_id),
        )
        await db.commit()
    return new_until.isoformat()


async def set_trial_flag(telegram_id: int, is_trial: bool) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET is_trial = ? WHERE telegram_id = ?",
            (1 if is_trial else 0, telegram_id),
        )
        await db.commit()


async def set_status(telegram_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET status = ? WHERE telegram_id = ?", (status, telegram_id)
        )
        await db.commit()


async def set_last_reminder(telegram_id: int, date_str: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET last_reminder_at = ? WHERE telegram_id = ?",
            (date_str, telegram_id),
        )
        await db.commit()


async def create_invoice_record(invoice_id: int, telegram_id: int, amount: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO invoices (invoice_id, telegram_id, amount, status, created_at) "
            "VALUES (?, ?, ?, 'active', ?)",
            (invoice_id, telegram_id, amount, now_iso()),
        )
        await db.commit()


async def get_invoice(invoice_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def mark_invoice_paid(invoice_id: int) -> bool:
    """Возвращает True, если это первая обработка оплаты (защита от повторов)."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT status FROM invoices WHERE invoice_id = ?", (invoice_id,)
        )
        row = await cur.fetchone()
        if not row or row["status"] == "paid":
            return False
        await db.execute(
            "UPDATE invoices SET status = 'paid', paid_at = ? WHERE invoice_id = ?",
            (now_iso(), invoice_id),
        )
        await db.commit()
        return True


async def get_pending_invoices(max_age_days: int = 3) -> list[dict]:
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM invoices WHERE status = 'active' AND created_at > ?",
            (cutoff,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def users_needing_reminder(days_before: int) -> list[dict]:
    today = dt.datetime.now(dt.timezone.utc)
    now_str = today.isoformat()
    threshold = (today + dt.timedelta(days=days_before)).isoformat()
    today_str = today.date().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE status = 'active' AND paid_until IS NOT NULL "
            "AND paid_until > ? AND paid_until <= ? "
            "AND (last_reminder_at IS NULL OR last_reminder_at != ?)",
            (now_str, threshold, today_str),
        )
        return [dict(r) for r in await cur.fetchall()]


async def users_to_kick(grace_period_days: int) -> list[dict]:
    cutoff = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=grace_period_days)
    ).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM users WHERE status = 'active' AND paid_until IS NOT NULL "
            "AND paid_until < ?",
            (cutoff,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_price(telegram_id: int, default_price: str) -> str:
    """Индивидуальная цена пользователя, если задана, иначе — дефолтная."""
    user = await get_user(telegram_id)
    if user and user.get("custom_price_usd"):
        return user["custom_price_usd"]
    return default_price


async def set_custom_price(telegram_id: int, price: str | None) -> None:
    """price=None сбрасывает персональную цену обратно на дефолтную."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET custom_price_usd = ? WHERE telegram_id = ?",
            (price, telegram_id),
        )
        await db.commit()


async def get_all_users() -> list[dict]:
    """Полный список для выгрузки — /list в admin.py."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT telegram_id, username, status, paid_until, custom_price_usd, is_trial, created_at "
            "FROM users ORDER BY "
            "CASE status WHEN 'active' THEN 0 WHEN 'expired' THEN 1 ELSE 2 END, "
            "paid_until IS NULL, paid_until"
        )
        return [dict(r) for r in await cur.fetchall()]


async def stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        active = (
            await (
                await db.execute("SELECT COUNT(*) c FROM users WHERE status='active'")
            ).fetchone()
        )["c"]
        expired = (
            await (
                await db.execute("SELECT COUNT(*) c FROM users WHERE status='expired'")
            ).fetchone()
        )["c"]
        total = (await (await db.execute("SELECT COUNT(*) c FROM users")).fetchone())["c"]
        month_start = dt.datetime.now(dt.timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).isoformat()
        paid_this_month = (
            await (
                await db.execute(
                    "SELECT COUNT(*) c, COALESCE(SUM(CAST(amount AS REAL)),0) s "
                    "FROM invoices WHERE status='paid' AND paid_at > ?",
                    (month_start,),
                )
            ).fetchone()
        )
        return {
            "active": active,
            "expired": expired,
            "total": total,
            "paid_count_month": paid_this_month["c"],
            "revenue_month": paid_this_month["s"],
        }
