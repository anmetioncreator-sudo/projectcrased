"""
backend/main.py - Key Verification Server for Susano Executor
Database: Prisma + SQLite (or PostgreSQL via schema.prisma)
Discord: Webhook Logging & Defense Alerts
"""

import os
import sys
import base64
import hashlib
import secrets
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse
from jinja2 import Environment, FileSystemLoader
from prisma import Prisma

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
load_dotenv(dotenv_path=BASE / ".env")

from webhooks import send_ban_unban_webhook, send_ip_log_webhook, send_login_webhook

# ── Configuration from .env ───────────────────────────────────────────────────
ADMIN_PATH     = os.getenv("ADMIN_PATH", "crased2026")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme123")
ADMIN_HASH     = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
XOR_SECRET     = os.getenv("XOR_SECRET", "xK9mQ2pL8nR3vT5w")

BROWSER_UA = ["Mozilla", "Chrome", "Safari", "Firefox", "Opera", "Edge", "Trident"]

# ── Prisma Client & Lifespan ──────────────────────────────────────────────────
def _init_sqlite_if_needed(db_file: Path):
    try:
        db_file.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_file))
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS "Key" (
            "id" TEXT NOT NULL PRIMARY KEY,
            "key" TEXT NOT NULL UNIQUE,
            "owner" TEXT NOT NULL,
            "scriptId" TEXT NOT NULL,
            "lockedIp" TEXT,
            "banned" BOOLEAN NOT NULL DEFAULT 0,
            "banReason" TEXT,
            "expires" DATETIME,
            "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS "BannedIp" (
            "id" TEXT NOT NULL PRIMARY KEY,
            "ip" TEXT NOT NULL UNIQUE,
            "reason" TEXT NOT NULL,
            "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS "AccessLog" (
            "id" TEXT NOT NULL PRIMARY KEY,
            "ip" TEXT NOT NULL,
            "key" TEXT NOT NULL,
            "result" TEXT NOT NULL,
            "reason" TEXT NOT NULL,
            "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS "Script" (
            "id" TEXT NOT NULL PRIMARY KEY,
            "scriptId" TEXT NOT NULL UNIQUE,
            "code" TEXT NOT NULL,
            "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO "Script" ("id", "scriptId", "code", "updatedAt") 
        VALUES ('script_default', 'default', 'print("Susano Executor Loaded Successfully!")', CURRENT_TIMESTAMP);
        INSERT OR IGNORE INTO "Key" ("id", "key", "owner", "scriptId") 
        VALUES ('key_demo', 'CRSED-DEMO-2026', 'Admin', 'default');
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database setup error: {e}", file=sys.stderr)

is_serverless = "VERCEL" in os.environ or bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if is_serverless:
    db_file = Path("/tmp/dev.db")
    _init_sqlite_if_needed(db_file)
    db_url = f"file:{db_file}"
    os.environ["DATABASE_URL"] = db_url
else:
    raw_url = os.getenv("DATABASE_URL", f"file:{BASE / 'dev.db'}")
    if raw_url.startswith("file:"):
        p_str = raw_url.replace("file:", "")
        local_path = Path(p_str)
        if not local_path.is_absolute():
            local_path = BASE / local_path
        _init_sqlite_if_needed(local_path)
    db_url = raw_url

db = Prisma(datasource={"url": db_url})

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    yield
    await db.disconnect()

app  = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

@app.middleware("http")
async def ensure_db_connected(request: Request, call_next):
    if not db.is_connected():
        await db.connect()
    return await call_next(request)

_env = Environment(loader=FileSystemLoader(str(BASE / "templates")), autoescape=True)
SESSIONS: set = set()

def _render(tmpl: str, **ctx) -> HTMLResponse:
    return HTMLResponse(_env.get_template(tmpl).render(**ctx))

def _is_browser(req: Request) -> bool:
    return any(s in req.headers.get("User-Agent", "") for s in BROWSER_UA)

def _is_admin(req: Request) -> bool:
    return req.cookies.get("admin_session") in SESSIONS

def _get_ip(req: Request) -> str:
    fwd = req.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "0.0.0.0")

def xor_encrypt(data: str, key: str) -> bytes:
    kb  = key.encode()
    raw = data.encode("utf-8")
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw))

async def _log(ip: str, key: str, result: str, reason: str = ""):
    await db.accesslog.create(data={"ip": ip, "key": key, "result": result, "reason": reason})
    await send_ip_log_webhook(ip, key, result, reason)

async def _ban_ip(ip: str, reason: str, actor: str = "Auto-Defense"):
    await db.bannedip.upsert(
        where={"ip": ip},
        data={"create": {"ip": ip, "reason": reason}, "update": {"reason": reason}}
    )
    await send_ban_unban_webhook("BAN", "IP", ip, reason, actor=actor)

async def _ban_key(key: str, reason: str, actor: str = "Auto-Defense"):
    await db.key.update_many(where={"key": key}, data={"banned": True, "banReason": reason})
    await send_ban_unban_webhook("BAN", "KEY", key, reason, actor=actor)

async def _is_banned_ip(ip: str) -> bool:
    return await db.bannedip.find_unique(where={"ip": ip}) is not None

# ═════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.get(f"/panel/{ADMIN_PATH}", response_class=HTMLResponse)
async def login_get(request: Request):
    if _is_admin(request):
        return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard")
    return _render("login.html", error=None)

@app.post(f"/panel/{ADMIN_PATH}", response_class=HTMLResponse)
async def login_post(request: Request, password: str = Form(...)):
    ip = _get_ip(request)
    if hashlib.sha256(password.encode()).hexdigest() == ADMIN_HASH:
        tok = secrets.token_hex(32)
        SESSIONS.add(tok)
        await send_login_webhook(ip, True, "Admin successfully authenticated")
        resp = RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)
        resp.set_cookie("admin_session", tok, httponly=True, samesite="strict")
        return resp
    
    await send_login_webhook(ip, False, "Incorrect password attempt")
    return _render("login.html", error="Wrong password")

@app.get(f"/panel/{ADMIN_PATH}/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _is_admin(request):
        return RedirectResponse(f"/panel/{ADMIN_PATH}")
    keys    = await db.key.find_many(order={"createdAt": "desc"})
    banned  = await db.bannedip.find_many(order={"createdAt": "desc"})
    log     = await db.accesslog.find_many(order={"createdAt": "desc"}, take=100)
    scripts = await db.script.find_many(order={"updatedAt": "desc"})
    return _render("dashboard.html",
                   keys=keys, banned_ips=banned, access_log=log,
                   scripts=[s.scriptId for s in scripts],
                   ADMIN_PATH=ADMIN_PATH)

# ── Key Management ────────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/keys/create")
async def key_create(request: Request,
                     key: str = Form(...), owner: str = Form(...), script_id: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.key.upsert(
        where={"key": key},
        data={"create": {"key": key, "owner": owner, "scriptId": script_id},
              "update": {"owner": owner, "scriptId": script_id}}
    )
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/ban")
async def key_ban(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await _ban_key(key, "Banned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/unban")
async def key_unban(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"banned": False, "banReason": None})
    await send_ban_unban_webhook("UNBAN", "KEY", key, "Unbanned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/delete")
async def key_delete(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.key.delete_many(where={"key": key})
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/unlock")
async def key_unlock(request: Request, key: str = Form(...)):
    """Reset IP lock - use when a player changes network."""
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"lockedIp": None})
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

# ── IP Management ─────────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/ips/unban")
async def ip_unban(request: Request, ip: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.bannedip.delete_many(where={"ip": ip})
    await send_ban_unban_webhook("UNBAN", "IP", ip, "Unbanned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

# ── Script Management ─────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/scripts/save")
async def script_save(request: Request, script_id: str = Form(...), code: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    safe = "".join(c for c in script_id if c.isalnum() or c in "-_")
    await db.script.upsert(
        where={"scriptId": safe},
        data={"create": {"scriptId": safe, "code": code}, "update": {"code": code}}
    )
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)

@app.get(f"/panel/{ADMIN_PATH}/scripts/get")
async def script_get(request: Request, id: str = ""):
    if not _is_admin(request): raise HTTPException(403)
    safe   = "".join(c for c in id if c.isalnum() or c in "-_")
    script = await db.script.find_unique(where={"scriptId": safe})
    return PlainTextResponse(script.code if script else "")

# ═════════════════════════════════════════════════════════════════════════════
#  API ENDPOINT  (Susano stub calls this)
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/execute")
async def api_execute(request: Request):
    ip = _get_ip(request)
    try:
        body = await request.json()
    except Exception:
        await _ban_ip(ip, "Malformed request to /api/execute", actor="Auto-Defense")
        await _log(ip, "", "BANNED", "Malformed request body")
        raise HTTPException(403)

    key = str(body.get("key", ""))

    # Trap browser visitors trying to inspect /api/execute
    if _is_browser(request):
        await _ban_ip(ip, "Browser UA detected on /api/execute", actor="Auto-Defense")
        if key:
            await _ban_key(key, "Key used from web browser - bypass attempt", actor="Auto-Defense")
        await _log(ip, key, "BANNED", "Browser UA on API route")
        raise HTTPException(403)

    # Check if IP is already banned
    if await _is_banned_ip(ip):
        await _log(ip, key, "BLOCKED", "IP is in active ban list")
        raise HTTPException(403)

    # Validate key existence
    entry = await db.key.find_unique(where={"key": key})
    if not entry:
        await _log(ip, key, "INVALID", "License key not found")
        raise HTTPException(403)

    if entry.banned:
        await _log(ip, key, "BANNED", entry.banReason or "Key banned")
        raise HTTPException(403)

    if entry.expires and datetime.now(timezone.utc) > entry.expires:
        await _log(ip, key, "EXPIRED", "Key expired")
        raise HTTPException(403)

    # IP Lock Enforcement: bind on first use, block sharing
    if entry.lockedIp and entry.lockedIp != ip:
        await _ban_ip(ip, f"IP mismatch - key was locked to {entry.lockedIp}", actor="IP-Lock Guard")
        await _ban_key(key, f"IP mismatch - key sharing detected (new IP: {ip})", actor="IP-Lock Guard")
        await _log(ip, key, "BANNED", f"IP lock violated (locked: {entry.lockedIp})")
        raise HTTPException(403)

    if not entry.lockedIp:
        await db.key.update(where={"id": entry.id}, data={"lockedIp": ip})
        await _log(ip, key, "LOCKED", f"Key successfully bound to IP {ip}")

    # Retrieve real Lua script from database
    script = await db.script.find_unique(where={"scriptId": entry.scriptId})
    if not script:
        await _log(ip, key, "ERROR", f"Script {entry.scriptId!r} not found in DB")
        raise HTTPException(500)

    # XOR encrypt script and base64 encode for secure transit
    encrypted = xor_encrypt(script.code, XOR_SECRET)
    encoded   = base64.b64encode(encrypted).decode()
    await _log(ip, key, "VALID", f"Script served: {entry.scriptId}")
    return PlainTextResponse(encoded)

# ═════════════════════════════════════════════════════════════════════════════
#  CATCH-ALL TRAP (Bans anyone snooping around the website)
# ═════════════════════════════════════════════════════════════════════════════

@app.api_route("/{path:path}",
               methods=["GET","POST","PUT","DELETE","HEAD","OPTIONS","PATCH"])
async def trap(request: Request, path: str):
    if path.startswith(f"panel/{ADMIN_PATH}"):
        raise HTTPException(404)
    ip = _get_ip(request)
    await _ban_ip(ip, f"Visited restricted endpoint: /{path}", actor="Trap Guard")
    await _log(ip, "", "BANNED", f"Browsed to: /{path}")
    raise HTTPException(403)