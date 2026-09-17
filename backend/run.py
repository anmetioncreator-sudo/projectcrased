"""
backend/run.py - Unified Launcher
Runs both the FastAPI Verification Gateway and the Discord Admin Bot concurrently.

Usage:
  py run.py          (Runs both server + Discord bot)
  py run.py --server (Runs server only)
  py run.py --bot    (Runs Discord bot only)
"""

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import argparse
import asyncio
import subprocess
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))
load_dotenv(dotenv_path=BASE_DIR / ".env")

def run_prisma_setup():
    """Ensures Prisma client is generated and DB is synced."""
    scripts_dir = str(Path(sys.executable).parent / "Scripts")
    if scripts_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{scripts_dir};{os.environ.get('PATH', '')}"

    print("[Prisma] Checking database & client...")
    try:
        subprocess.run([sys.executable, "-m", "prisma", "generate", "--schema", str(BASE_DIR / "schema.prisma")], check=False)
        subprocess.run([sys.executable, "-m", "prisma", "db", "push", "--schema", str(BASE_DIR / "schema.prisma")], check=False)
        print("[Prisma] Database and client ready.")
    except Exception as e:
        print(f"[Prisma Warning] Prisma setup step: {e}")

async def start_server():
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"[Server] Starting Uvicorn server on http://0.0.0.0:{port} ...", flush=True)
    config = uvicorn.Config("main:app", host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def start_bot():
    from bot import main as bot_main
    print("[Bot] Starting Discord bot...", flush=True)
    await bot_main()

async def run_both():
    run_prisma_setup()
    print("[Launcher] Starting both Gateway Server and Discord Bot concurrently...", flush=True)
    await asyncio.gather(
        start_server(),
        start_bot()
    )

def main():
    parser = argparse.ArgumentParser(description="Susano Gateway Launcher")
    parser.add_argument("--server", action="store_true", help="Run FastAPI server only")
    parser.add_argument("--bot", action="store_true", help="Run Discord bot only")
    args = parser.parse_args()

    if args.server:
        run_prisma_setup()
        asyncio.run(start_server())
    elif args.bot:
        run_prisma_setup()
        asyncio.run(start_bot())
    else:
        asyncio.run(run_both())

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[Launcher] Shutting down cleanly.")