import os
import sys
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

# On Vercel, use /tmp for SQLite database if DATABASE_URL is not set or local
if "VERCEL" in os.environ:
    tmp_db = Path("/tmp/dev.db")
    if not tmp_db.exists():
        local_db = BACKEND_DIR / "dev.db"
        if local_db.exists():
            import shutil
            shutil.copyfile(str(local_db), str(tmp_db))
    os.environ["DATABASE_URL"] = f"file:{tmp_db}"

from main import app