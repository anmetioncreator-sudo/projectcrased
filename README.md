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

## Live Vercel Deployment

The FastAPI Gateway is deployed live on Vercel:

- **Production URL:** `https://projectcrased.vercel.app`
- **Admin Panel:** `https://projectcrased.vercel.app/panel/crased2026`
- **Executor API Route:** `https://projectcrased.vercel.app/api/execute`
- **GitHub Repository:** [anmetioncreator-sudo/projectcrased](https://github.com/anmetioncreator-sudo/projectcrased)

> [!NOTE]
> The live Vercel gateway handles license verification, automatic IP locking, security traps, and triple Discord webhook alerts in real time.
> Because Vercel serverless functions do not support long-running background processes, run the Discord Bot separately (locally via `py run.py --bot` or 24/7 on Railway/Render using `python run.py`).

---

## Hosting Analysis: Vercel vs. Railway / Render / VPS

### Notes on Vercel Serverless:
1. **Serverless Execution:** Vercel functions run on demand per request. The HTTP gateway routes, IP defense trap, and webhook alerts function smoothly.
2. **Discord Bot:** A Discord bot requires a 24/7 continuous WebSocket gateway connection to Discord. Running the bot 24/7 is best done on Railway, Render, or a VPS.

### Recommended Hosts for 24/7 Server + Bot in One Container:
- **Railway.app** or **Render.com**:
  - Connect your GitHub repository `anmetioncreator-sudo/projectcrased`.
  - Set start command to `python run.py`.
  - Runs both the FastAPI gateway and Discord Bot 24/7 concurrently.
- **VPS (Ubuntu / Debian):**
  - Run with Docker (`Dockerfile` included in `backend/`) or `systemd`.