"""
backend/bot.py - Discord Bot for Susano Security & License Management
Provides Discord commands for:
  - Creating license keys (!createkey)
  - Banning / Unbanning keys and IPs (!ban, !unban)
  - Resetting IP locks (!unlock)
  - Viewing logs and statistics (!logs, !status, !keys, !bans)
  - Graceful stop (!stop)
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend path is in sys.path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

load_dotenv(dotenv_path=BASE_DIR / ".env")

import discord
from discord.ext import commands
from prisma import Prisma
from webhooks import send_ban_unban_webhook, send_ip_log_webhook

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
db = Prisma()

@bot.event
async def on_ready():
    print(f"==================================================")
    print(f"[Discord Bot] Logged in as: {bot.user} (ID: {bot.user.id})")
    print(f"[Discord Bot] Ready to manage licenses and defense.")
    print(f"==================================================")
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Susano Key Auth"))

@bot.command(name="help")
async def cmd_help(ctx):
    """Displays available admin commands."""
    embed = discord.Embed(
        title="🛡️ Susano Gateway Admin Bot",
        description="Available commands for license management and security:",
        color=0x5865F2
    )
    embed.add_field(name="!createkey <key> <owner> <script_id>", value="Creates a new key bound to a script.", inline=False)
    embed.add_field(name="!ban <key_or_ip> [reason]", value="Bans an IP or license key instantly.", inline=False)
    embed.add_field(name="!unban <key_or_ip>", value="Unbans an IP or license key.", inline=False)
    embed.add_field(name="!unlock <key>", value="Resets the IP lock for a key (allows new machine).", inline=False)
    embed.add_field(name="!keys", value="Displays a list of registered license keys.", inline=False)
    embed.add_field(name="!bans", value="Lists all currently banned IPs.", inline=False)
    embed.add_field(name="!logs [limit]", value="Views recent access and defense logs.", inline=False)
    embed.add_field(name="!status", value="Displays server and license system health stats.", inline=False)
    embed.add_field(name="!stop", value="Stops the Discord bot cleanly.", inline=False)
    embed.set_footer(text="Susano License Guard")
    await ctx.send(embed=embed)

@bot.command(name="createkey")
async def cmd_createkey(ctx, key: str, owner: str, script_id: str = "example"):
    """Creates a new license key."""
    try:
        # Check if script exists
        script = await db.script.find_unique(where={"scriptId": script_id})
        if not script:
            await ctx.send(f"⚠️ Warning: Script ID `{script_id}` is not currently uploaded in the database. Key created anyway.")

        entry = await db.key.upsert(
            where={"key": key},
            data={
                "create": {"key": key, "owner": owner, "scriptId": script_id},
                "update": {"owner": owner, "scriptId": script_id, "banned": False}
            }
        )

        embed = discord.Embed(
            title="🔑 License Key Created",
            color=0x57F287,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Key", value=f"`{entry.key}`", inline=True)
        embed.add_field(name="Owner", value=f"`{entry.owner}`", inline=True)
        embed.add_field(name="Script", value=f"`{entry.scriptId}`", inline=True)
        embed.add_field(name="Status", value="`ACTIVE (Unlocked)`", inline=True)
        embed.add_field(name="Instructions", value="Paste this key into `KEY` inside `stub.lua`.", inline=False)
        embed.set_footer(text=f"Created by {ctx.author.name}")

        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error creating key: `{e}`")

ADMIN_IPS = {ip.strip() for ip in os.getenv("ADMIN_IPS", "103.79.178.41").split(",") if ip.strip()}

@bot.command(name="stopkey", aliases=["stop_key", "pausekey"])
async def cmd_stopkey(ctx, key: str):
    """Stops/pauses a key without permanent ban."""
    try:
        entry = await db.key.find_unique(where={"key": key})
        if not entry:
            await ctx.send(f"⚠️ License key `{key}` not found in database.")
            return
        await db.key.update(
            where={"key": key},
            data={"banned": True, "banReason": "Stopped by Admin"}
        )
        await send_ban_unban_webhook("STOP", "KEY", key, f"Stopped by Discord Admin {ctx.author.name}", actor=f"Discord Admin: {ctx.author.name}")
        await ctx.send(f"⏸️ **Key Stopped:** `{key}` (Owner: `{entry.owner}`). Use `!startkey {key}` to resume.")
    except Exception as e:
        await ctx.send(f"❌ Error stopping key: `{e}`")

@bot.command(name="startkey", aliases=["resumekey", "activatekey"])
async def cmd_startkey(ctx, key: str):
    """Resumes/activates a stopped or banned key."""
    try:
        entry = await db.key.find_unique(where={"key": key})
        if not entry:
            await ctx.send(f"⚠️ License key `{key}` not found in database.")
            return
        await db.key.update(
            where={"key": key},
            data={"banned": False, "banReason": None}
        )
        await send_ban_unban_webhook("START", "KEY", key, f"Activated by Discord Admin {ctx.author.name}", actor=f"Discord Admin: {ctx.author.name}")
        await ctx.send(f"▶️ **Key Activated:** `{key}` (Owner: `{entry.owner}`) is now active and ready to use.")
    except Exception as e:
        await ctx.send(f"❌ Error activating key: `{e}`")

@bot.command(name="ban")
async def cmd_ban(ctx, target: str, *, reason: str = "Manual admin ban"):
    """Bans either an IP address or a license key."""
    try:
        # Determine if target is IP or Key
        is_ip = "." in target and not target.upper().startswith("KEY-")
        if is_ip:
            if target in ADMIN_IPS:
                await ctx.send(f"🛡️ **Blocked:** `{target}` is registered as an Admin IP and cannot be banned.")
                return
            await db.bannedip.upsert(
                where={"ip": target},
                data={"create": {"ip": target, "reason": reason}, "update": {"reason": reason}}
            )
            await send_ban_unban_webhook("BAN", "IP", target, reason, actor=f"Discord Admin: {ctx.author.name}")
            await ctx.send(f"🚨 **IP Banned:** `{target}` - Reason: `{reason}`")
        else:
            entry = await db.key.find_unique(where={"key": target})
            if not entry:
                await ctx.send(f"⚠️ License key `{target}` not found in database.")
                return
            await db.key.update(
                where={"key": target},
                data={"banned": True, "banReason": reason}
            )
            await send_ban_unban_webhook("BAN", "KEY", target, reason, actor=f"Discord Admin: {ctx.author.name}")
            await ctx.send(f"🚨 **Key Banned:** `{target}` (Owner: `{entry.owner}`) - Reason: `{reason}`")
    except Exception as e:
        await ctx.send(f"❌ Error executing ban: `{e}`")

@bot.command(name="unban")
async def cmd_unban(ctx, target: str):
    """Unbans an IP address or license key."""
    try:
        is_ip = "." in target and not target.upper().startswith("KEY-")
        if is_ip:
            del_result = await db.bannedip.delete_many(where={"ip": target})
            if del_result > 0:
                await send_ban_unban_webhook("UNBAN", "IP", target, "Unbanned by admin", actor=f"Discord Admin: {ctx.author.name}")
                await ctx.send(f"✅ **IP Unbanned:** `{target}`")
            else:
                await ctx.send(f"ℹ️ IP `{target}` was not in the ban list.")
        else:
            entry = await db.key.find_unique(where={"key": target})
            if not entry:
                await ctx.send(f"⚠️ License key `{target}` not found.")
                return
            await db.key.update(
                where={"key": target},
                data={"banned": False, "banReason": None}
            )
            await send_ban_unban_webhook("UNBAN", "KEY", target, "Unbanned by admin", actor=f"Discord Admin: {ctx.author.name}")
            await ctx.send(f"✅ **Key Unbanned:** `{target}` (Owner: `{entry.owner}`)")
    except Exception as e:
        await ctx.send(f"❌ Error executing unban: `{e}`")

@bot.command(name="unlock")
async def cmd_unlock(ctx, key: str):
    """Resets the IP lock for a key so customer can use on a new connection."""
    try:
        entry = await db.key.find_unique(where={"key": key})
        if not entry:
            await ctx.send(f"⚠️ Key `{key}` not found.")
            return
        await db.key.update(where={"key": key}, data={"lockedIp": None})
        await ctx.send(f"🔓 **IP Lock Cleared:** Key `{key}` (Owner: `{entry.owner}`) is now unlocked for next use.")
    except Exception as e:
        await ctx.send(f"❌ Error unlocking key: `{e}`")

@bot.command(name="keys")
async def cmd_keys(ctx):
    """Lists registered keys."""
    try:
        keys = await db.key.find_many(order={"createdAt": "desc"}, take=25)
        if not keys:
            await ctx.send("ℹ️ No license keys registered in database.")
            return

        embed = discord.Embed(
            title=f"🔑 License Keys ({len(keys)})",
            color=0x3498DB,
            timestamp=datetime.now(timezone.utc)
        )
        for k in keys:
            status = "🔴 BANNED" if k.banned else "🟢 ACTIVE"
            lock = f"🔒 `{k.lockedIp}`" if k.lockedIp else "🔓 Unlocked"
            embed.add_field(
                name=f"{k.key} [{status}]",
                value=f"Owner: `{k.owner}` | Script: `{k.scriptId}`\nIP Lock: {lock}",
                inline=False
            )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error fetching keys: `{e}`")

@bot.command(name="bans")
async def cmd_bans(ctx):
    """Lists banned IPs."""
    try:
        banned = await db.bannedip.find_many(order={"createdAt": "desc"}, take=25)
        if not banned:
            await ctx.send("✅ No IPs are currently banned.")
            return

        embed = discord.Embed(
            title=f"🚨 Banned IPs ({len(banned)})",
            color=0xED4245,
            timestamp=datetime.now(timezone.utc)
        )
        for b in banned:
            embed.add_field(
                name=f"IP: `{b.ip}`",
                value=f"Reason: `{b.reason}`\nDate: `{b.createdAt.strftime('%Y-%m-%d %H:%M:%S')}`",
                inline=False
            )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error fetching bans: `{e}`")

@bot.command(name="logs")
async def cmd_logs(ctx, limit: int = 10):
    """Shows recent access logs."""
    limit = max(1, min(limit, 20))
    try:
        logs = await db.accesslog.find_many(order={"createdAt": "desc"}, take=limit)
        if not logs:
            await ctx.send("ℹ️ No access logs recorded yet.")
            return

        embed = discord.Embed(
            title=f"📋 Recent Access Logs (Last {len(logs)})",
            color=0x2ECC71,
            timestamp=datetime.now(timezone.utc)
        )
        for entry in logs:
            embed.add_field(
                name=f"[{entry.result}] {entry.ip} - {entry.createdAt.strftime('%H:%M:%S')}",
                value=f"Key: `{entry.key or 'N/A'}`\nDetails: `{entry.reason or 'N/A'}`",
                inline=False
            )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error fetching logs: `{e}`")

@bot.command(name="status")
async def cmd_status(ctx):
    """Displays system health and database statistics."""
    try:
        total_keys = await db.key.count()
        banned_keys = await db.key.count(where={"banned": True})
        total_bans = await db.bannedip.count()
        total_logs = await db.accesslog.count()
        total_scripts = await db.script.count()

        embed = discord.Embed(
            title="📊 Susano Gateway Status",
            color=0x9B59B6,
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name="Total Keys", value=f"`{total_keys}`", inline=True)
        embed.add_field(name="Active Keys", value=f"`{total_keys - banned_keys}`", inline=True)
        embed.add_field(name="Banned Keys", value=f"`{banned_keys}`", inline=True)
        embed.add_field(name="Banned IPs", value=f"`{total_bans}`", inline=True)
        embed.add_field(name="Saved Scripts", value=f"`{total_scripts}`", inline=True)
        embed.add_field(name="Logged Events", value=f"`{total_logs}`", inline=True)
        embed.set_footer(text="System Operational")
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error fetching status: `{e}`")

@bot.command(name="stop")
async def cmd_stop(ctx):
    """Cleanly stops the Discord bot."""
    await ctx.send("🛑 Stopping Susano Discord Bot...")
    await bot.close()

async def main():
    if not BOT_TOKEN or "YOUR_" in BOT_TOKEN:
        print("[Bot Error] DISCORD_BOT_TOKEN is not configured in .env file!", flush=True)
        return

    print("[Bot] Connecting to Prisma database...", flush=True)
    if not db.is_connected():
        await db.connect()
    try:
        print("[Bot] Starting Discord bot...", flush=True)
        await bot.start(BOT_TOKEN)
    except Exception as e:
        print(f"[Bot Exception] {e}", flush=True)
    finally:
        print("[Bot] Disconnecting from database...", flush=True)
        if db.is_connected():
            await db.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Bot] Shutting down.")