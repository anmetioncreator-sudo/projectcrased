"""
backend/webhooks.py - Discord Webhook Notifier
Sends rich embeds for ban/unban events, IP connection logs, and admin logins.
"""

import os
import httpx
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BAN_UNBAN_WEBHOOK = os.getenv("DISCORD_WEBHOOK_BAN_UNBAN", "")
IP_LOG_WEBHOOK    = os.getenv("DISCORD_WEBHOOK_IP", "")
LOGIN_WEBHOOK     = os.getenv("DISCORD_WEBHOOK_LOGIN", "")

async def _post_embed(url: str, title: str, description: str, color: int, fields: list = None):
    if not url:
        return
    
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": "Susano Security Gateway"
        }
    }
    if fields:
        embed["fields"] = fields

    payload = {
        "username": "Susano Gateway Alert",
        "embeds": [embed]
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(url, json=payload)
    except Exception as e:
        print(f"[Webhook Error] Failed to send webhook to {url[:40]}... : {e}")

async def send_ban_unban_webhook(action: str, target_type: str, target_val: str, reason: str = "", actor: str = "System"):
    """
    Sends embed to the BAN/UNBAN webhook channel.
    action: 'BAN' or 'UNBAN'
    target_type: 'IP' or 'KEY'
    """
    is_ban = action.upper() == "BAN"
    color = 0xED4245 if is_ban else 0x57F287  # Red for Ban, Green for Unban
    icon = "🚨" if is_ban else "✅"

    title = f"{icon} {action.upper()} Event: {target_type.upper()}"
    description = f"A **{action.upper()}** action was executed against a {target_type.lower()}."

    fields = [
        {"name": f"Target {target_type}", "value": f"`{target_val}`", "inline": True},
        {"name": "Triggered By", "value": f"`{actor}`", "inline": True},
        {"name": "Reason", "value": f"```{reason or 'No reason provided'}```", "inline": False},
    ]

    await _post_embed(BAN_UNBAN_WEBHOOK, title, description, color, fields)

async def send_ip_log_webhook(ip: str, key: str = "", result: str = "", reason: str = ""):
    """
    Sends embed to the IP logs webhook channel.
    """
    res_upper = result.upper()
    if res_upper in ("VALID", "LOCKED"):
        color = 0x57F287  # Green
        icon = "🟢"
    elif res_upper in ("BANNED", "BLOCKED"):
        color = 0xED4245  # Red
        icon = "🔴"
    else:
        color = 0xFEE75C  # Yellow
        icon = "🟡"

    title = f"{icon} IP Traffic Activity [{res_upper}]"
    description = f"Inbound connection handled by security filter."

    fields = [
        {"name": "IP Address", "value": f"`{ip}`", "inline": True},
        {"name": "License Key", "value": f"`{key or 'N/A'}`", "inline": True},
        {"name": "Result", "value": f"**{res_upper}**", "inline": True},
        {"name": "Details", "value": f"`{reason or 'N/A'}`", "inline": False},
    ]

    await _post_embed(IP_LOG_WEBHOOK, title, description, color, fields)

async def send_login_webhook(ip: str, success: bool, reason: str = ""):
    """
    Sends embed to the Admin Login webhook channel.
    """
    color = 0x57F287 if success else 0xED4245
    status_text = "SUCCESSFUL LOGIN" if success else "FAILED LOGIN ATTEMPT"
    icon = "🛡️" if success else "⚠️"

    title = f"{icon} Admin Panel Access: {status_text}"
    description = f"An authentication attempt was registered for the admin panel."

    fields = [
        {"name": "Source IP", "value": f"`{ip}`", "inline": True},
        {"name": "Status", "value": f"`{'SUCCESS' if success else 'REJECTED'}`", "inline": True},
        {"name": "Details", "value": f"`{reason or ('Authenticated via admin password' if success else 'Invalid credentials')}`", "inline": False}
    ]

    await _post_embed(LOGIN_WEBHOOK, title, description, color, fields)