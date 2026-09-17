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
from datetime import datetime, timezone, timedelta
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, PlainTextResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader
from prisma import Prisma

BASE = Path(__file__).parent
sys.path.insert(0, str(BASE))
load_dotenv(dotenv_path=BASE / ".env")

from webhooks import send_ban_unban_webhook, send_ip_log_webhook, send_login_webhook

# ── Configuration from .env ───────────────────────────────────────────────────
ADMIN_PATH     = os.getenv("ADMIN_PATH", "dsadsaadmin").strip().strip('"').strip("'")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "31986282").strip().strip('"').strip("'")
ADMIN_HASH     = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
XOR_SECRET     = os.getenv("XOR_SECRET", "xK9mQ2pL8nR3vT5w")
ADMIN_IPS      = [ip.strip() for ip in os.getenv("ADMIN_IPS", "103.79.178.41,103.79.179.2,103.79.").split(",") if ip.strip()]

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
        DELETE FROM "BannedIp" WHERE "ip" LIKE '103.79.%' OR "ip" = '103.79.178.41';
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Database setup error: {e}", file=sys.stderr)

is_serverless = "VERCEL" in os.environ or bool(os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))
if is_serverless:
    db_file = Path("/tmp/dev.db")
    _init_sqlite_if_needed(db_file)
    db_url = f"file:{db_file.resolve()}"
    os.environ["DATABASE_URL"] = db_url
else:
    raw_url = os.getenv("DATABASE_URL", f"file:{BASE / 'dev.db'}")
    if raw_url.startswith("file:"):
        p_str = raw_url.replace("file:", "")
        local_path = Path(p_str)
        if not local_path.is_absolute():
            local_path = (BASE / local_path).resolve()
        _init_sqlite_if_needed(local_path)
        db_url = f"file:{local_path.resolve()}"
    else:
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
    if is_serverless:
        _init_sqlite_if_needed(Path("/tmp/dev.db"))
    if not db.is_connected():
        await db.connect()
    return await call_next(request)

_env = Environment(loader=FileSystemLoader(str(BASE / "templates")), autoescape=True)
SESSIONS: set = set()

def _render(tmpl: str, **ctx) -> HTMLResponse:
    return HTMLResponse(_env.get_template(tmpl).render(**ctx))

def _is_browser(req: Request) -> bool:
    return any(s in req.headers.get("User-Agent", "") for s in BROWSER_UA)

def _get_ip(req: Request) -> str:
    fwd = req.headers.get("X-Forwarded-For")
    return fwd.split(",")[0].strip() if fwd else (req.client.host if req.client else "0.0.0.0")

def _is_admin_ip(ip: str) -> bool:
    if not ip or ip == "0.0.0.0":
        return False
    for p in ADMIN_IPS:
        if p.endswith(".") and ip.startswith(p):
            return True
        if ip == p:
            return True
    return False

def _is_admin(req: Request) -> bool:
    return _is_admin_ip(_get_ip(req)) or req.cookies.get("admin_session") in SESSIONS

def xor_encrypt(data: str, key: str) -> bytes:
    kb  = key.encode()
    raw = data.encode("utf-8")
    return bytes(b ^ kb[i % len(kb)] for i, b in enumerate(raw))

async def _log(ip: str, key: str, result: str, reason: str = ""):
    await db.accesslog.create(data={"ip": ip, "key": key, "result": result, "reason": reason})
    await send_ip_log_webhook(ip, key, result, reason)

async def _ban_ip(ip: str, reason: str, actor: str = "Auto-Defense"):
    if _is_admin_ip(ip):
        return  # Admin IP is permanently immune to bans
    await db.bannedip.upsert(
        where={"ip": ip},
        data={"create": {"ip": ip, "reason": reason}, "update": {"reason": reason}}
    )
    await send_ban_unban_webhook("BAN", "IP", ip, reason, actor=actor)

async def _ban_key(key: str, reason: str, actor: str = "Auto-Defense"):
    await db.key.update_many(where={"key": key}, data={"banned": True, "banReason": reason})
    await send_ban_unban_webhook("BAN", "KEY", key, reason, actor=actor)

async def _is_banned_ip(ip: str) -> bool:
    if _is_admin_ip(ip):
        return False  # Admin IP is never considered banned
    return await db.bannedip.find_unique(where={"ip": ip}) is not None

# ═════════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.get(f"/panel/{ADMIN_PATH}", response_class=HTMLResponse)
async def login_get(request: Request):
    if _is_admin(request):
        tok = secrets.token_hex(32)
        SESSIONS.add(tok)
        resp = RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)
        resp.set_cookie("admin_session", tok, max_age=30*86400, httponly=True, samesite="lax", path="/")
        return resp
    return _render("login.html", error=None)

@app.post(f"/panel/{ADMIN_PATH}", response_class=HTMLResponse)
async def login_post(request: Request, password: str = Form(...)):
    ip = _get_ip(request)
    if hashlib.sha256(password.encode()).hexdigest() == ADMIN_HASH:
        tok = secrets.token_hex(32)
        SESSIONS.add(tok)
        await send_login_webhook(ip, True, "Admin successfully authenticated")
        resp = RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)
        resp.set_cookie("admin_session", tok, max_age=30*86400, httponly=True, samesite="lax", path="/")
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
    server_url = os.getenv("SERVER_URL", "https://projectcrased.vercel.app").rstrip("/")
    return _render("dashboard.html",
                   keys=keys, banned_ips=banned, access_log=log,
                   scripts=scripts,
                   ADMIN_PATH=ADMIN_PATH,
                   ADMIN_PASSWORD=ADMIN_PASSWORD,
                   XOR_SECRET=XOR_SECRET,
                   SERVER_URL=server_url)

# ── Key Management ────────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/keys/create")
async def key_create(request: Request,
                     key: str = Form(""),
                     owner: str = Form(...),
                     script_id: str = Form(...),
                     hours: str = Form("")):
    if not _is_admin(request): raise HTTPException(403)
    target_key = key.strip().upper()
    if not target_key:
        target_key = f"CRSED-{secrets.token_hex(3).upper()}-{secrets.token_hex(3).upper()}"
    exp = None
    if hours and hours.strip().isdigit() and int(hours.strip()) > 0:
        exp = datetime.now(timezone.utc) + timedelta(hours=int(hours.strip()))
    await db.key.upsert(
        where={"key": target_key},
        data={"create": {"key": target_key, "owner": owner.strip(), "scriptId": script_id.strip(), "expires": exp},
              "update": {"owner": owner.strip(), "scriptId": script_id.strip(), "expires": exp}}
    )
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/stop")
async def key_stop(request: Request, key: str = Form(...)):
    """Stops/pauses a key without permanent ban."""
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"banned": True, "banReason": "Stopped by Admin"})
    await send_ban_unban_webhook("STOP", "KEY", key, "Key stopped/paused by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/start")
async def key_start(request: Request, key: str = Form(...)):
    """Resumes/activates a stopped or banned key."""
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"banned": False, "banReason": None})
    await send_ban_unban_webhook("START", "KEY", key, "Key activated/resumed by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/ban")
async def key_ban(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await _ban_key(key, "Banned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/unban")
async def key_unban(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"banned": False, "banReason": None})
    await send_ban_unban_webhook("UNBAN", "KEY", key, "Unbanned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/delete")
async def key_delete(request: Request, key: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.key.delete_many(where={"key": key})
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/keys/unlock")
async def key_unlock(request: Request, key: str = Form(...)):
    """Reset IP lock - use when a player changes network."""
    if not _is_admin(request): raise HTTPException(403)
    await db.key.update_many(where={"key": key}, data={"lockedIp": None})
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#keys", status_code=302)

# ── IP Management ─────────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/ips/ban")
async def ip_ban_manual(request: Request, ip: str = Form(...), reason: str = Form("Manual Admin Ban")):
    if not _is_admin(request): raise HTTPException(403)
    target = ip.strip()
    if target and not _is_admin_ip(target):
        await _ban_ip(target, reason, actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#bans", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/ips/unban")
async def ip_unban(request: Request, ip: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    await db.bannedip.delete_many(where={"ip": ip})
    await send_ban_unban_webhook("UNBAN", "IP", ip, "Unbanned by admin panel", actor="Admin Panel")
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#bans", status_code=302)

# ── Script Management ─────────────────────────────────────────────────────────

@app.post(f"/panel/{ADMIN_PATH}/scripts/save")
async def script_save(request: Request, script_id: str = Form(...), code: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    safe = "".join(c for c in script_id if c.isalnum() or c in "-_")
    await db.script.upsert(
        where={"scriptId": safe},
        data={"create": {"scriptId": safe, "code": code}, "update": {"code": code}}
    )
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#scripts", status_code=302)

@app.post(f"/panel/{ADMIN_PATH}/scripts/delete")
async def script_delete(request: Request, script_id: str = Form(...)):
    if not _is_admin(request): raise HTTPException(403)
    safe = "".join(c for c in script_id if c.isalnum() or c in "-_")
    await db.script.delete_many(where={"scriptId": safe})
    return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard#scripts", status_code=302)

@app.get(f"/panel/{ADMIN_PATH}/scripts/get")
async def script_get(request: Request, id: str = ""):
    if not _is_admin(request): raise HTTPException(403)
    safe   = "".join(c for c in id if c.isalnum() or c in "-_")
    script = await db.script.find_unique(where={"scriptId": safe})
    return PlainTextResponse(script.code if script else "")

@app.get(f"/panel/{ADMIN_PATH}/loader")
async def get_loader(request: Request, key: str = "", script_id: str = ""):
    if not _is_admin(request): raise HTTPException(403)
    server_url = os.getenv("SERVER_URL", "https://projectcrased.vercel.app").rstrip("/")
    target_key = key or "YOUR_KEY_HERE"
    target_script = script_id or "default"
    
    universal_loader = f"""-- ==========================================================
--  PROJECT CRASED SECURE LOADER
--  Key: {target_key} | Script: {target_script}
-- ==========================================================
local KEY = "{target_key}"
local SERVER = "{server_url}"
local XOR_SECRET = "{XOR_SECRET}"

local http_req = (syn and syn.request) or (http and http.request) or http_request or (fluxus and fluxus.request) or request or (getgenv and getgenv().request)
if not http_req then
    error("[CRSED] Your executor does not support standard HTTP requests.")
end

local response = http_req({{
    Url = SERVER .. "/api/execute",
    Method = "POST",
    Headers = {{
        ["Content-Type"] = "application/json",
        ["User-Agent"]   = "Susano/1.0"
    }},
    Body = '{{"key":"' .. KEY .. '"}}'
}})

if not response or response.StatusCode ~= 200 then
    error("[CRSED] Verification failed (HTTP " .. tostring(response and response.StatusCode or "FAIL") .. "). Contact support.")
end

local _B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function _b64dec(s)
    s = s:gsub("[^" .. _B64 .. "=]", "")
    local out = {{}}
    for i = 1, #s, 4 do
        local function v(c)
            if not c or c == "=" then return 0 end
            return (_B64:find(c, 1, true) or 1) - 1
        end
        local a, b, c, d = v(s:sub(i, i)), v(s:sub(i+1, i+1)), v(s:sub(i+2, i+2)), v(s:sub(i+3, i+3))
        local n = a * 262144 + b * 4096 + c * 64 + d
        out[#out+1] = string.char(math.floor(n / 65536) % 256)
        if s:sub(i+2, i+2) ~= "=" then out[#out+1] = string.char(math.floor(n / 256) % 256) end
        if s:sub(i+3, i+3) ~= "=" then out[#out+1] = string.char(n % 256) end
    end
    return table.concat(out)
end

local function _xdec(data, kstr)
    local r, kb = {{}}, {{}}
    for i = 1, #kstr do kb[i] = kstr:byte(i) end
    for i = 1, #data do
        local b = data:byte(i)
        local k = kb[((i - 1) % #kb) + 1]
        local bx = (bit32 and bit32.bxor) or (bit and bit.bxor) or function(x, y)
            local p, c = 1, 0
            while x > 0 or y > 0 do
                local rx, ry = x % 2, y % 2
                if rx ~= ry then c = c + p end
                x, y, p = math.floor(x / 2), math.floor(y / 2), p * 2
            end
            return c
        end
        r[i] = string.char(bx(b, k))
    end
    return table.concat(r)
end

local ok1, raw = pcall(_b64dec, response.Body)
if not ok1 then error("[CRSED] Payload decode error") end

local ok2, decrypted = pcall(_xdec, raw, XOR_SECRET)
if not ok2 then error("[CRSED] Payload decrypt error") end

local fn, err = loadstring(decrypted)
if not fn then
    if Susano and Susano.InjectResource then
        Susano.InjectResource("any", decrypted, Susano.NEW_THREAD)
    else
        error("[CRSED] Loadstring error: " .. tostring(err))
    end
else
    fn()
end"""

    fivem_loader = f"""-- ==========================================================
--  SUSANO / FIVEM STUB LOADER
--  Key: {target_key} | Script: {target_script}
-- ==========================================================
local KEY = "{target_key}"
local SERVER = "{server_url}"
local _XK = "{XOR_SECRET}"
local INJECT_TARGET = "any"

local _B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function _b64dec(s)
    s = s:gsub("[^" .. _B64 .. "=]", "")
    local out = {{}}
    for i = 1, #s, 4 do
        local function v(c)
            if not c or c == "=" then return 0 end
            return (_B64:find(c, 1, true) or 1) - 1
        end
        local a, b, c, d = v(s:sub(i, i)), v(s:sub(i+1, i+1)), v(s:sub(i+2, i+2)), v(s:sub(i+3, i+3))
        local n = a * 262144 + b * 4096 + c * 64 + d
        out[#out+1] = string.char(math.floor(n / 65536) % 256)
        if s:sub(i+2, i+2) ~= "=" then out[#out+1] = string.char(math.floor(n / 256) % 256) end
        if s:sub(i+3, i+3) ~= "=" then out[#out+1] = string.char(n % 256) end
    end
    return table.concat(out)
end

local function _xdec(data, kstr)
    local r, kb = {{}}, {{}}
    for i = 1, #kstr do kb[i] = kstr:byte(i) end
    for i = 1, #data do
        local b = data:byte(i)
        local k = kb[((i - 1) % #kb) + 1]
        local bx = (bit32 and bit32.bxor) or (bit and bit.bxor) or function(x, y)
            local p, c = 1, 0
            while x > 0 or y > 0 do
                local rx, ry = x % 2, y % 2
                if rx ~= ry then c = c + p end
                x, y, p = math.floor(x / 2), math.floor(y / 2), p * 2
            end
            return c
        end
        r[i] = string.char(bx(b, k))
    end
    return table.concat(r)
end

local status, response = Susano.HttpPost(
    SERVER .. "/api/execute",
    string.format('{{"key":"%s"}}', KEY),
    {{
        ["Content-Type"] = "application/json",
        ["User-Agent"]   = "Susano/1.0"
    }}
)

if status ~= 200 then
    print("[Stub] Auth error: " .. tostring(status))
    return
end

local ok1, decoded = pcall(_b64dec, response)
if not ok1 then return end
local ok2, decrypted = pcall(_xdec, decoded, _XK)
if not ok2 then return end

Susano.InjectResource(INJECT_TARGET, decrypted, Susano.NEW_THREAD)"""

    return JSONResponse({
        "key": target_key,
        "scriptId": target_script,
        "universal": universal_loader,
        "fivem": fivem_loader
    })

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
#  CATCH-ALL TRAP & ROOT ROUTE
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/")
async def root_index(request: Request):
    ip = _get_ip(request)
    if _is_admin_ip(ip):
        return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)
    await _ban_ip(ip, "Visited root index", actor="Trap Guard")
    await _log(ip, "", "BANNED", "Browsed to: /")
    raise HTTPException(403)

@app.api_route("/{path:path}",
               methods=["GET","POST","PUT","DELETE","HEAD","OPTIONS","PATCH"])
async def trap(request: Request, path: str):
    ip = _get_ip(request)
    clean = path.strip("/")
    if _is_admin_ip(ip):
        if clean.startswith(f"panel/{ADMIN_PATH}"):
            raise HTTPException(404)
        return RedirectResponse(f"/panel/{ADMIN_PATH}/dashboard", status_code=302)
    if clean.startswith(f"panel/{ADMIN_PATH}"):
        raise HTTPException(404)
    await _ban_ip(ip, f"Visited restricted endpoint: /{path}", actor="Trap Guard")
    await _log(ip, "", "BANNED", f"Browsed to: /{path}")
    raise HTTPException(403)