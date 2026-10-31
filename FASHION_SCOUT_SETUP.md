# VYN Fashion Scout — Telegram Cloud Bot

Initial version tests Telegram delivery only. It does not search for products yet.

## GitHub secrets
In Settings > Secrets and variables > Actions add:
- TELEGRAM_BOT_TOKEN (BotFather secret)
- TELEGRAM_CHAT_ID (your numeric Telegram user ID)

Open Actions > VYN Fashion Scout > Run workflow to send a test message.

Next: integrate an authorized product feed with actual prices, shipping, fees, and comparable sold prices. Only then enable scheduled scans and alerts. Never commit secrets.
