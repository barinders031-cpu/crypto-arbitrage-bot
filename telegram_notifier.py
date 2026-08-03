"""
Telegram Notification Helper for Arbitrage Bot
Sends instant alerts whenever a cross-exchange arbitrage trade is executed.
"""

import urllib.request
import urllib.parse
import json
import os

CONFIG_FILE = "telegram_config.json"

DEFAULT_BOT_TOKEN = "8978722164:AAFjyciRunvcl-zPQdv4yZCAYdWAVDP08Ss"
DEFAULT_CHAT_ID   = "511891548"


def get_telegram_credentials():
    possible_paths = [
        CONFIG_FILE,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE),
        "e:/nse/telegram_config.json"
    ]
    for path in possible_paths:
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                    if data.get("bot_token") and data.get("chat_id"):
                        return data
            except Exception:
                pass

    # Fallback to Environment Variables or Defaults
    env_token   = os.getenv("TELEGRAM_BOT_TOKEN", DEFAULT_BOT_TOKEN)
    env_chat_id = os.getenv("TELEGRAM_CHAT_ID", DEFAULT_CHAT_ID)
    env_enabled = os.getenv("TELEGRAM_ENABLED", "true").lower() != "false"

    return {
        "bot_token": env_token.strip(),
        "chat_id": env_chat_id.strip(),
        "enabled": env_enabled
    }


def save_telegram_credentials(bot_token, chat_id, enabled=True):
    data = {
        "bot_token": bot_token.strip(),
        "chat_id": chat_id.strip(),
        "enabled": enabled
    }
    for path in [CONFIG_FILE, os.path.join(os.path.dirname(os.path.abspath(__file__)), CONFIG_FILE)]:
        try:
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass
    return data


def send_telegram_alert(message_text: str) -> bool:
    creds = get_telegram_credentials()
    token = creds.get("bot_token")
    chat_id = creds.get("chat_id")
    enabled = creds.get("enabled", True)

    if not enabled or not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Attempt 1: Try with Markdown formatting
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
        if res.status == 200:
            return True
    except Exception:
        pass

    # Attempt 2: Plain text fallback if Markdown parsing fails (e.g. unescaped entities)
    try:
        payload_plain = {
            "chat_id": chat_id,
            "text": message_text
        }
        req2 = urllib.request.Request(
            url,
            data=json.dumps(payload_plain).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        res2 = urllib.request.urlopen(req2, timeout=5)
        return res2.status == 200
    except Exception as e:
        print(f"Telegram notification error: {e}")
        return False
