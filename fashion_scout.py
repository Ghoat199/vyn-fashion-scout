"""Fashion Snipe alert worker.

Reads only a user-configured, authorized HTTPS JSON feed. It does not scrape
Vinted or Kleinanzeigen, bypass logins, or place orders.
"""
import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation
from pathlib import Path

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
FEED_URL = os.getenv("PRODUCT_FEED_URL", "")
MAX_COST = Decimal(os.getenv("MAX_TOTAL_COST_EUR", "40"))
MIN_PROFIT = Decimal(os.getenv("MIN_PROFIT_EUR", "12"))
STATE_FILE = Path("seen_offers.json")
ALLOWED_WORDS = (
    "kleidung", "shirt", "t-shirt", "hoodie", "sweatshirt", "jacke",
    "hose", "jeans", "pullover", "mantel", "kleid", "rock", "bluse",
    "sneaker", "schuhe", "stiefel", "boots", "turnschuhe", "sportschuhe",
    "nike", "adidas", "jordan", "new balance", "puma", "asics",
    "carhartt", "stone island", "ralph lauren", "lacoste", "tommy hilfiger",
    "the north face", "patagonia", "vintage"
)

def decimal_value(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() and result >= 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None

def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN oder TELEGRAM_CHAT_ID fehlt.")
    payload = json.dumps({"chat_id": CHAT_ID, "text": message, "disable_web_page_preview": True}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram hat die Nachricht nicht bestätigt.")

def load_seen():
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(data if isinstance(data, list) else [])
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen(seen):
    # Keep the most recent 5,000 offer keys.
    STATE_FILE.write_text(json.dumps(sorted(seen)[-5000:], ensure_ascii=False, indent=2), encoding="utf-8")

def scan():
    if not FEED_URL:
        print("Kein autorisierter Produkt-Feed konfiguriert. Keine Marktplatzsuche ausgeführt.")
        return
    if not FEED_URL.startswith("https://"):
        raise ValueError("PRODUCT_FEED_URL muss HTTPS verwenden.")
    request = urllib.request.Request(FEED_URL, headers={"User-Agent": "FashionSnipe/0.1"})
    with urllib.request.urlopen(request, timeout=25) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("Produkt-Feed ist größer als 2 MB.")
    products = json.loads(raw)
    if not isinstance(products, list):
        raise ValueError("Der Produkt-Feed muss ein JSON-Array sein.")

    seen = load_seen()
    new_seen = set(seen)
    sent = 0
    checked = 0
    for product in products[:500]:
        if not isinstance(product, dict):
            continue
        title = str(product.get("title", "")).strip()
        category = str(product.get("category", "")).strip()
        searchable = (title + " " + category).casefold()
        if not title or not any(word in searchable for word in ALLOWED_WORDS):
            continue

        price = decimal_value(product.get("price"))
        shipping = decimal_value(product.get("shipping", 0))
        resale = decimal_value(product.get("resale_estimate"))
        selling_fees = decimal_value(product.get("selling_fees", 0))
        outbound_shipping = decimal_value(product.get("outbound_shipping", 0))
        url = product.get("url", "")
        if any(v is None for v in (price, shipping, resale, selling_fees, outbound_shipping)):
            continue
        if not isinstance(url, str) or not url.startswith("https://"):
            continue

        checked += 1
        total_cost = price + shipping
        estimated_profit = resale - total_cost - selling_fees - outbound_shipping
        if total_cost > MAX_COST or estimated_profit < MIN_PROFIT:
            continue

        offer_key = str(product.get("id") or url)
        if offer_key in seen:
            continue

        platform = str(product.get("platform", "Angebotsquelle"))
        size = str(product.get("size", "Nicht angegeben"))
        brand = str(product.get("brand", ""))
        message = (
            "👟 Fashion Snipe – möglicher Deal\n\n"
            f"{title}\n"
            f"Plattform: {platform}\n"
            f"Marke: {brand or 'Nicht angegeben'}\n"
            f"Größe: {size}\n"
            f"Kauf + Versand: {total_cost:.2f} €\n"
            f"Geschätzter Verkauf: {resale:.2f} €\n"
            f"Geschätzter Überschuss: {estimated_profit:.2f} €\n\n"
            f"{url}\n\n"
            "Hinweis: Schätzwert aus dem Feed, kein garantierter Gewinn. Echtheit, Zustand und Marktpreis selbst prüfen."
        )
        send_telegram(message)
        new_seen.add(offer_key)
        sent += 1

    save_seen(new_seen)
    print(f"Feed geprüft: {checked} passende Fashion-Artikel; Telegram-Meldungen: {sent}.")

def main():
    if os.getenv("TEST_TELEGRAM") == "1":
        send_telegram("✅ Fashion Snipe: Telegram-Verbindung funktioniert. Fashion-Feed ist separat einzurichten.")
        print("Telegram-Test erfolgreich.")
        return
    scan()

if __name__ == "__main__":
    main()
