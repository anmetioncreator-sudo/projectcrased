import os
import sys
import sqlite3
import subprocess
from pathlib import Path

# Add backend to Python path
BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = BASE_DIR / "backend"
sys.path.insert(0, str(BACKEND_DIR))

# Ensure Prisma client is generated
try:
    from prisma import Prisma
except Exception:
    subprocess.run(
        [sys.executable, "-m", "prisma", "generate", "--schema", str(BACKEND_DIR / "schema.prisma")],
        check=False
    )

# On Vercel / serverless, ensure SQLite db exists and schema is prepared
if "VERCEL" in os.environ or not os.environ.get("DATABASE_URL"):
    tmp_db = Path("/tmp/dev.db") if "VERCEL" in os.environ else BACKEND_DIR / "dev.db"
    os.environ["DATABASE_URL"] = f"file:{tmp_db}"
    try:
        conn = sqlite3.connect(str(tmp_db))
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
        print(f"DB Init warning: {e}", file=sys.stderr)

from main import app