-- ╔══════════════════════════════════════════════════════════════╗
-- ║           SUSANO STUB  —  DO NOT SHARE THIS FILE            ║
-- ║      Each customer receives a unique stub with their key     ║
-- ╚══════════════════════════════════════════════════════════════╝

-- ── CONFIGURE (one file per customer, key changes per person) ──
local KEY    = "CRSED-DEMO-2026"
local SERVER = "https://projectcrased.vercel.app"

-- ── XOR secret — MUST match XOR_SECRET in backend/main.py ─────
local _XK = "xK9mQ2pL8nR3vT5w"

-- ── Inject target — "any" works on all servers ─────────────────
--    Change to a specific resource name if needed, e.g. "es_extended"
local INJECT_TARGET = "any"

-- ══════════════════════════════════════════════════════════════
--  INTERNALS — do not edit below this line
-- ══════════════════════════════════════════════════════════════

-- Base64 decode (pure Lua, no external deps)
local _B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
local function _b64dec(s)
    s = s:gsub("[^" .. _B64 .. "=]", "")
    local out = {}
    for i = 1, #s, 4 do
        local function v(c)
            if not c or c == "=" then return 0 end
            return (_B64:find(c, 1, true) or 1) - 1
        end
        local a = v(s:sub(i,   i))
        local b = v(s:sub(i+1, i+1))
        local c = v(s:sub(i+2, i+2))
        local d = v(s:sub(i+3, i+3))
        local n = a * 262144 + b * 4096 + c * 64 + d
        out[#out+1] = string.char(n >> 16 & 0xFF)
        if s:sub(i+2, i+2) ~= "=" then out[#out+1] = string.char(n >> 8 & 0xFF) end
        if s:sub(i+3, i+3) ~= "=" then out[#out+1] = string.char(n & 0xFF) end
    end
    return table.concat(out)
end

-- XOR decrypt
local function _xdec(data, key)
    local r, kb = {}, {}
    for i = 1, #key do kb[i] = key:byte(i) end
    for i = 1, #data do
        r[i] = string.char(data:byte(i) ~ kb[((i - 1) % #kb) + 1])
    end
    return table.concat(r)
end

-- ── Run ────────────────────────────────────────────────────────
print("[Stub] Verifying license...")

if KEY == "YOUR-LICENSE-KEY-HERE" or KEY == "" then
    print("[Stub] ERROR: No license key set at top of stub.")
    return
end

-- Build JSON body
local body = string.format('{"key":"%s"}', KEY)

-- POST to server — synchronous (Susano blocks until done)
local status, response = Susano.HttpPost(
    SERVER .. "/api/execute",
    body,
    {
        ["Content-Type"] = "application/json",
        ["User-Agent"]   = "Susano/1.0"
    }
)

-- Check response
if not status then
    print("[Stub] ERROR: Could not reach server — " .. tostring(response))
    return
end

if status ~= 200 then
    print("[Stub] Authorization failed (HTTP " .. tostring(status) .. "). Contact admin.")
    return
end

if not response or #response == 0 then
    print("[Stub] ERROR: Empty response from server.")
    return
end

-- Decode: base64 → XOR decrypt → real Lua
local ok1, decoded   = pcall(_b64dec, response)
if not ok1 then print("[Stub] Decode error: " .. tostring(decoded)) return end

local ok2, decrypted = pcall(_xdec, decoded, _XK)
if not ok2 then print("[Stub] Decrypt error: " .. tostring(decrypted)) return end

-- Inject into FiveM resource
print("[Stub] License valid. Injecting script...")

local ok3, err = pcall(function()
    Susano.InjectResource(INJECT_TARGET, decrypted, Susano.NEW_THREAD)
end)

if ok3 then
    print("[Stub] Script injected successfully.")
else
    print("[Stub] Injection error: " .. tostring(err))
end
