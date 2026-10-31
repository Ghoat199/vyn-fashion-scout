import os
import json
import urllib.request

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

def send(message):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in GitHub Actions secrets")
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = json.dumps({"chat_id": CHAT_ID, "text": message}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return json.load(response)

def main():
    # No fabricated listings. Connect an authorized product feed before scheduling scans.
    if os.getenv("TEST_TELEGRAM") == "1":
        send("✅ VYN Fashion Scout: Telegram-Verbindung funktioniert! Noch keine Produktsuche aktiv.")
    else:
        print("Product feed not configured; no listings sent.")

if __name__ == "__main__":
    main()
