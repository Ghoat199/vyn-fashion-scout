import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FEED_URL = os.getenv("PRODUCT_FEED_URL", "")
MAX_COST = Decimal("50")
MIN_PROFIT = Decimal("10")

def money(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return None

def send(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Telegram secrets are missing")
    payload = json.dumps({"chat_id": CHAT_ID, "text": message}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)

def scan():
    if not FEED_URL:
        print("No authorized PRODUCT_FEED_URL configured; skipping scan.")
        return
    if not FEED_URL.startswith("https://"):
        raise ValueError("Product feed must use HTTPS")
    request = urllib.request.Request(FEED_URL, headers={"User-Agent": "VYNFashionScout/1.0"})
    with urllib.request.urlopen(request, timeout=25) as response:
        if int(response.headers.get("Content-Length", "0")) > 2_000_000:
            raise ValueError("Feed too large")
        data = json.loads(response.read(2_000_001))
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of products")
    candidates = []
    for product in data[:500]:
        if not isinstance(product, dict):
            continue
        price = money(product.get("price"))
        shipping = money(product.get("shipping"))
        resale = money(product.get("resale_estimate"))
        fees = money(product.get("selling_fees"))
        outbound = money(product.get("outbound_shipping"))
        url = product.get("url", "")
        if any(v is None or v < 0 for v in (price, shipping, resale, fees, outbound)):
            continue
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        cost = price + shipping
        profit = resale - cost - fees - outbound
        if cost <= MAX_COST and profit >= MIN_PROFIT:
            candidates.append((profit, product, cost))
    # Feed estimates are not verified sold prices. Do not send purchase alerts until validated.
    print(f"{len(candidates)} candidates from feed; alerts disabled pending price validation.")

def main():
    if os.getenv("TEST_TELEGRAM") == "1":
        send("✅ VYN Fashion Scout: Telegram-Verbindung funktioniert! Noch keine Produktsuche aktiv.")
    else:
        scan()

if __name__ == "__main__":
    main()
