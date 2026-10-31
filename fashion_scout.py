import json
import os
import urllib.request
from decimal import Decimal, InvalidOperation

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FEED_URL = os.getenv("PRODUCT_FEED_URL", "")
MAX_COST = Decimal("20")
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


def discover_godalo():
    """Use MCP initialization before tool discovery; diagnostic only."""
    endpoint = "https://mcp.godalo.ai/mcp"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
        "User-Agent": "VYNFashionScout/1.2",
    }

    def request(method, params=None, request_id=1, session=None):
        data = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            data["id"] = request_id
        if params is not None:
            data["params"] = params
        current_headers = dict(headers)
        if session:
            current_headers["Mcp-Session-Id"] = session
        req = urllib.request.Request(endpoint, data=json.dumps(data).encode(), headers=current_headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            session_id = response.headers.get("Mcp-Session-Id", session)
            body = response.read(200000).decode("utf-8")
            content_type = response.headers.get("Content-Type", "")
        if "text/event-stream" in content_type:
            events = [line[6:] for line in body.splitlines() if line.startswith("data:")]
            messages = [json.loads(line) for line in events if line.strip() and line.strip() != "[DONE]"]
            result = next((m for m in messages if "result" in m or "error" in m), {})
        else:
            result = json.loads(body) if body.strip() else {}
        if "error" in result:
            raise RuntimeError("MCP error: " + str(result["error"])[:300])
        return result, session_id

    initialized, session = request("initialize", {
        "protocolVersion": "2025-11-25",
        "capabilities": {},
        "clientInfo": {"name": "vyn-fashion-scout", "version": "1.2.1"}
    })
    print("Godalo initialized:", initialized.get("result", {}).get("protocolVersion", "unknown"))
    request("notifications/initialized", request_id=None, session=session)
    discovered, _ = request("tools/list", params={}, request_id=2, session=session)
    tools = discovered.get("result", {}).get("tools", [])
    print("Godalo tools:", [tool.get("name") for tool in tools])
    for tool in tools:
        if tool.get("name") in ("get_deals", "get_recommendations"):
            print("Godalo schema", tool["name"], json.dumps(tool.get("inputSchema", {}), ensure_ascii=False)[:4000])
    if not tools:
        print("Godalo returned no tools.")
        return

    def call_tool(name, arguments, request_id):
        result, _ = request("tools/call", {"name": name, "arguments": arguments},
                            request_id=request_id, session=session)
        if result.get("result", {}).get("isError"):
            print("Godalo tool error:", name)
            return
        data = result.get("result", {}).get("content", [])
        # Diagnostic output only: never send unverified resale claims to Telegram.
        for part in data[:3]:
            if part.get("type") == "text":
                print("Godalo", name, "response:", str(part.get("text", ""))[:5000])
                print("NOTE: Listed discounts are not verified resale profits; shipping and fees unknown.")

    try:
        print("Godalo get_deals request started", flush=True)
        call_tool("get_deals", {
            "country": "DE", "category": "fashion", "budget": 20, "min_discount": 30
        }, 3)
        print("Godalo get_deals request completed", flush=True)
    except Exception as exc:
        print(f"Godalo get_deals failed: {type(exc).__name__}: {exc}", flush=True)
        print("No product alerts sent; will retry at next scheduled run.", flush=True)

def main():
    if os.getenv("TEST_TELEGRAM") == "1":
        send("✅ VYN Fashion Scout: Telegram-Verbindung funktioniert! Noch keine Produktsuche aktiv.")
    else:
        scan()
        if os.getenv("ENABLE_GODALO_DISCOVERY") == "1":
            try:
                discover_godalo()
            except Exception as exc:
                print(f"Godalo discovery unavailable: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    main()
