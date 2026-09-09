"""
Тонкая обёртка над Crypto Pay API (@CryptoBot).
Документация: https://help.send.tg/en/articles/10279948-crypto-pay-api
"""
import hashlib
import hmac
import json

import httpx

from config import ACCEPTED_ASSETS, CRYPTO_PAY_API_URL, CRYPTO_PAY_TOKEN, INVOICE_EXPIRES_IN


class CryptoPayError(RuntimeError):
    pass


async def _request(method: str, params: dict) -> dict:
    url = f"{CRYPTO_PAY_API_URL}/{method}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(url, headers=headers, json=params)
    data = resp.json()
    if not data.get("ok"):
        raise CryptoPayError(f"{method} failed: {data.get('error')}")
    return data["result"]


async def create_invoice(amount_usd: str, telegram_id: int, description: str,
                          paid_btn_url: str | None = None) -> dict:
    params = {
        "currency_type": "fiat",
        "fiat": "USD",
        "accepted_assets": ACCEPTED_ASSETS,
        "amount": amount_usd,
        "description": description,
        "payload": str(telegram_id),
        "expires_in": INVOICE_EXPIRES_IN,
        "allow_comments": False,
    }
    if paid_btn_url:
        params["paid_btn_name"] = "openBot"
        params["paid_btn_url"] = paid_btn_url
    return await _request("createInvoice", params)


async def get_invoices(invoice_ids: list[int]) -> list[dict]:
    if not invoice_ids:
        return []
    params = {"invoice_ids": ",".join(str(i) for i in invoice_ids)}
    result = await _request("getInvoices", params)
    return result.get("items", [])


def verify_webhook_signature(body: bytes, signature_header: str) -> bool:
    secret = hashlib.sha256(CRYPTO_PAY_TOKEN.encode()).digest()
    computed = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature_header or "")
