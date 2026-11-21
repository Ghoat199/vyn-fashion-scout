"""Fashion Snipe: authorized API-backed fashion listing alerts."""
import json
import os
import re
import statistics
import urllib.parse
import urllib.request
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
APISH_KEY = os.getenv("APISH_API_KEY", "")
SCAVIO_KEY = os.getenv("SCAVIO_API_KEY", "")
MAX_COST = Decimal(os.getenv("MAX_TOTAL_COST_EUR", "15"))
STATE_FILE = Path("seen_offers.json")

# One search per marketplace per run. Rotate terms to conserve Scavio's credits.
SEARCH_TERMS = [
    "Nike", "Adidas", "Jordan", "New Balance", "Carhartt",
    "Stone Island", "Ralph Lauren", "The North Face",
    "Patagonia", "Lacoste", "Tommy Hilfiger", "Sneaker"
]
ALLOWED_WORDS = (
    "shirt", "t-shirt", "hoodie", "sweatshirt", "jacke", "hose", "jeans",
    "pullover", "mantel", "kleid", "rock", "bluse", "sneaker", "schuhe",
    "stiefel", "boots", "turnschuhe", "sportschuhe", "nike", "adidas",
    "jordan", "new balance", "puma", "asics", "carhartt", "stone island",
    "ralph lauren", "lacoste", "tommy hilfiger", "the north face",
    "patagonia", "vintage"
)

def dec(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("amount"))
    try:
        number = Decimal(str(value).replace(",", "."))
        return number if number.is_finite() and number >= 0 else None
    except (InvalidOperation, TypeError, ValueError, AttributeError):
        return None

def request_json(url, headers, payload=None, timeout=60):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="GET" if payload is None else "POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(4_000_001)
    if len(raw) > 4_000_000:
        raise ValueError("API-Antwort ist größer als 4 MB.")
    result = json.loads(raw)
    if isinstance(result, dict) and result.get("success") is False:
        raise RuntimeError(str(result.get("error", "API meldet einen Fehler")))
    return result

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram-Secrets fehlen.")
    body = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=20) as response:
        result = json.load(response)
    if not result.get("ok"):
        raise RuntimeError("Telegram hat die Nachricht nicht bestätigt.")

def load_seen():
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return set(value if isinstance(value, list) else [])
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen)[-10000:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

def unwrap_items(response, platform):
    # Provider response wrappers may evolve; accept their documented list containers.
    current = response
    for _ in range(4):
        if isinstance(current, list):
            return current
        if not isinstance(current, dict):
            return []
        for key in ("items", "results", "ads", "listings"):
            value = current.get(key)
            if isinstance(value, list):
                return value
        next_value = current.get("data")
        if next_value is None:
            break
        current = next_value
    return []

def normalize(item, platform):
    if not isinstance(item, dict):
        return None
    title = str(item.get("title") or item.get("name") or "").strip()
    url = item.get("url") or item.get("link") or item.get("item_url") or ""
    price = dec(item.get("total_price", item.get("price", item.get("price_value"))))
    if not title or not isinstance(url, str) or not url.startswith("https://") or price is None:
        return None
    search_text = title.casefold()
    if not any(word in search_text for word in ALLOWED_WORDS):
        return None
    currency = str(item.get("currency") or "EUR").upper()
    if currency != "EUR":
        return None
    brand = item.get("brand") or ""
    if isinstance(brand, dict):
        brand = brand.get("title") or brand.get("name") or ""
    size = item.get("size") or item.get("size_title") or "Nicht angegeben"
    item_id = item.get("id") or item.get("ad_id") or item.get("adid") or url
    return {
        "id": f"{platform}:{item_id}",
        "title": title,
        "url": url,
        "price": price,
        "platform": platform,
        "brand": str(brand),
        "size": str(size),
    }

def search_vinted(term):
    if not SCAVIO_KEY:
        print("SCAVIO_API_KEY fehlt – Vinted übersprungen.")
        return []
    response = request_json(
        "https://api.scavio.dev/api/v1/vinted/search",
        {
            "Authorization": f"Bearer {SCAVIO_KEY}",
            "Content-Type": "application/json",
        },
        {"country": "de", "query": term, "sort": "newest_first", "page": 1},
    )
    return [p for p in (normalize(x, "Vinted") for x in unwrap_items(response, "Vinted")) if p]

def search_kleinanzeigen(term):
    if not APISH_KEY:
        print("APISH_API_KEY fehlt – Kleinanzeigen übersprungen.")
        return []
    query = urllib.parse.urlencode({"q": term, "sort": "newest"})
    response = request_json(
        f"https://api.api.sh/kleinanzeigen/v1/search?{query}",
        {"x-api-key": APISH_KEY, "Accept": "application/json"},
    )
    return [p for p in (normalize(x, "Kleinanzeigen") for x in unwrap_items(response, "Kleinanzeigen")) if p]


def category_for(title):
    value = title.casefold()
    groups = {
        "Sneaker/Schuhe": ("sneaker", "schuh", "boots", "stiefel", "turnschuh"),
        "Jacke": ("jacke", "jacket", "coat", "mantel", "parka"),
        "Hose": ("hose", "jeans", "trouser", "pants"),
        "Oberteil": ("shirt", "t-shirt", "hoodie", "sweatshirt", "pullover", "sweater", "bluse"),
    }
    for category, words in groups.items():
        if any(word in value for word in words):
            return category
    return "Sonstige"

def comparable_estimate(item, all_items):
    # Compare only listings from the same search batch. These are asking prices,
    # not confirmed completed-sale prices.
    words = set(re.findall(r"[a-z0-9]+", item["title"].casefold()))
    ignored = {"the", "and", "mit", "für", "neu", "new", "top", "sehr", "gut", "größe"}
    words -= ignored
    category = category_for(item["title"])
    brand = item["brand"].casefold().strip()
    matches = []
    for other in all_items:
        if other["id"] == item["id"] or other["platform"] == item["platform"]:
            continue
        if category_for(other["title"]) != category:
            continue
        other_brand = other["brand"].casefold().strip()
        if brand and other_brand and brand != other_brand:
            continue
        other_words = set(re.findall(r"[a-z0-9]+", other["title"].casefold())) - ignored
        overlap = len(words & other_words) / max(1, len(words | other_words))
        same_brand = bool(brand and other_brand and brand == other_brand)
        if overlap >= 0.25 or same_brand:
            matches.append(other["price"])
    if len(matches) < 2:
        return None, len(matches)
    return Decimal(str(statistics.median(matches))).quantize(Decimal("0.01")), len(matches)

def main():
    if os.getenv("TEST_TELEGRAM") == "1":
        send_telegram("✅ Fashion Snipe: Telegram-Verbindung funktioniert.")
        print("Telegram-Test erfolgreich.")
        return

    # Stable daily rotation: one search request per marketplace per scheduled run.
    term = SEARCH_TERMS[date.today().toordinal() % len(SEARCH_TERMS)]
    print(f"Suche nach: {term}")
    results = []
    errors = []
    for label, fn in (("Vinted", search_vinted), ("Kleinanzeigen", search_kleinanzeigen)):
        try:
            found = fn(term)
            print(f"{label}: {len(found)} passende Treffer.")
            results.extend(found)
        except Exception as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
            print(f"{label}-Fehler: {type(exc).__name__}: {exc}")

    seen = load_seen()
    new_seen = set(seen)
    sent = 0
    for item in results:
        if item["id"] in seen or item["price"] > MAX_COST:
            continue
        resale, comparable_count = comparable_estimate(item, results)
        if resale is None:
            resale_text = "Noch keine zuverlässigen Vergleichsangebote"
            profit_text = "Nicht berechenbar"
        else:
            resale_text = f"Ca. {resale:.2f} € (Angebotspreise aus {comparable_count} Vergleichen)"
            profit_text = f"Ca. {resale - item['price']:.2f} € vor Gebühren und Versand"
        message = (
            "🧥 Fashion Snipe – neues Angebot\\n\\n"
            f"{item['title']}\\n"
            f"Plattform: {item['platform']}\\n"
            f"Marke: {item['brand'] or 'Nicht angegeben'}\\n"
            f"Größe: {item['size']}\\n"
            f"Kaufpreis: {item['price']:.2f} €\\n"
            f"Geschätzter Verkaufspreis: {resale_text}\\n"
            f"Möglicher Brutto-Gewinn: {profit_text}\\n\\n"
            f"{item['url']}\\n\\n"
            "Schätzung basiert auf ähnlichen aktiven Anzeigen, nicht auf bestätigten Verkäufen. Zustand, Nachfrage, Gebühren und Versand können den Erlös verändern."
        )
        send_telegram(message)
        new_seen.add(item["id"])
        sent += 1

    # Mark only processed items as seen; avoid hiding results if Telegram failed.
    save_seen(new_seen)
    print(f"Neue Telegram-Meldungen: {sent}.")
    if errors:
        raise RuntimeError("Mindestens eine Marktplatzsuche ist fehlgeschlagen: " + " | ".join(errors))

if __name__ == "__main__":
    main()
