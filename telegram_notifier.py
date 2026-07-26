"""
Telegram Notification Helper for Arbitrage Bot
Sends instant alerts whenever a cross-exchange arbitrage trade is executed.
"""

import urllib.request
import urllib.parse
import json
import os

CONFIG_FILE = "e:/nse/telegram_config.json"

def get_telegram_credentials():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"bot_token": "", "chat_id": "", "enabled": False}

def save_telegram_credentials(bot_token, chat_id, enabled=True):
    data = {
        "bot_token": bot_token.strip(),
        "chat_id": chat_id.strip(),
        "enabled": enabled
    }
    with open(CONFIG_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return data

def send_telegram_alert(message_text):
    creds = get_telegram_credentials()
    token = creds.get("bot_token")
    chat_id = creds.get("chat_id")
    enabled = creds.get("enabled", False)

    if not enabled or not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "Markdown"
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        res = urllib.request.urlopen(req, timeout=5)
        return res.status == 200
    except Exception as e:
        print(f"Telegram notification error: {e}")
        return False
