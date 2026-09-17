# Susano Gateway & License Verification System

Server-side Lua delivery, IP defense gateway, and Discord admin integration for the Susano FiveM executor.

## Architecture

```
                               ┌────────────────────────────────┐
                               │       Discord Server           │
                               │  - Webhook: Ban / Unban Logs   │
                               │  - Webhook: IP Traffic Logs    │
                               │  - Webhook: Admin Login Logs   │
                               │  - Bot: Key/Ban Management     │
                               └──────────────▲─────────────────┘
                                              │ Alerts & Commands
                                              ▼
┌──────────────────┐  Susano.HttpPost  ┌────────────────────────────────┐
│   Susano Lua     │ ────────────────► │        FastAPI Gateway         │
│   (stub.lua)     │ ◄──────────────── │   - Auto-Defense Trap          │
│                  │   XOR Encrypted   │   - IP Locking on first use    │
└──────────────────┘       Code        │   - Prisma Database (SQLite/PG)│
                                       └────────────────────────────────┘
```

---

## Features

- **Encrypted Delivery:** The real Lua script stays in the database and is never shared as a file.
- **IP Lock Enforcement:** The first player machine/IP to redeem a key is locked to it. If the key is shared or tested on another network, the key and IP are immediately banned.
- **Trap Defense:** Any web browser or crawler visiting any route (or trying to browse the API) is blocked with HTTP 403 and instantly added to the ban list.
- **Triple Discord Webhooks:**
  - **Ban / Unban Log Channel:** Instant embed alerts on all manual or auto bans/unbans.
  - **IP Traffic Log Channel:** Real-time log of every connection attempt, validity, and reasons.
  - **Admin Login Channel:** Alerts on every admin authentication attempt.
- **Discord Admin Bot:** Manage your entire system right from Discord:
  - `!createkey <key> <owner> [script_id]` — Create a license key.
  - `!ban <key_or_ip> [reason]` — Ban an IP or key immediately.
  - `!unban <key_or_ip>` — Unban an IP or key.
  - `!unlock <key>` — Clear the IP lock if a customer changed networks.
  - `!keys` — List registered keys and statuses.
  - `!bans` — List banned IPs.
  - `!logs [limit]` — View recent activity logs.
  - `!status` — View system and database statistics.
  - `!stop` — Gracefully stop the bot.

---

## Configuration (`.env`)

Create `backend/.env` (see `backend/.env.example`):

```env
# Discord Webhooks
DISCORD_WEBHOOK_BAN_UNBAN=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_IP=https://discord.com/api/webhooks/...
DISCORD_WEBHOOK_LOGIN=https://discord.com/api/webhooks/...

# Discord Bot Token
DISCORD_BOT_TOKEN=YOUR_BOT_TOKEN

# Admin Panel & Encryption
ADMIN_PATH=crased2026
ADMIN_PASSWORD=changeme123
XOR_SECRET=xK9mQ2pL8nR3vT5w
DATABASE_URL=file:./dev.db
PORT=8000
```

---

## Quick Start (Local)

1. **Install dependencies:**
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. **Generate Prisma client & sync DB:**
   ```bash
   python -m prisma generate --schema schema.prisma
   python -m prisma db push --schema schema.prisma
   ```

3. **Run Gateway Server & Discord Bot:**
   ```bash
   python run.py          # Runs both server & Discord bot
   python run.py --server # Runs FastAPI server only
   python run.py --bot    # Runs Discord bot only
   ```

---

## Hosting Analysis: Vercel vs. Railway / Render / VPS

### Why Vercel is NOT Recommended for this stack:
1. **Serverless Execution:** Vercel functions terminate after a few seconds of idle time. A **Discord Bot requires a 24/7 continuous WebSocket gateway connection** and will shut down immediately on Vercel.
2. **Ephemeral File System:** SQLite (`dev.db`) on Vercel is read-only and reset on every invocation. All registered keys, bans, and logs will be lost.

### Recommended Hosts for 24/7 Server + Bot:
- **Railway.app** or **Render.com** (Free / low-cost):
  - Directly connect your GitHub repository.
  - Runs 24/7 containers with persistent disk for SQLite (or 1-click PostgreSQL).
  - Starts both the FastAPI gateway and Discord Bot concurrently using `python run.py`.
- **VPS (Ubuntu / Debian):**
  - Run with `systemd` or Docker for 100% uptime and full control.