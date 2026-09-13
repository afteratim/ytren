import asyncio
import threading
import time
import os
import urllib.request

from flask import Flask, jsonify
from bot import run_bot
from config import SELF_PING_ENABLED, SELF_PING_INTERVAL

app = Flask(__name__)


@app.get("/")
def index():
    return "YouTube Audio Bot is running."


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


# ============================================================
# SELF PING
# ============================================================

def self_ping():
    if not SELF_PING_ENABLED:
        return

    service_url = os.getenv("RENDER_EXTERNAL_URL", "").strip()

    if not service_url:
        return

    health_url = service_url.rstrip("/") + "/health"

    # Give Gunicorn/Flask time to start.
    time.sleep(30)

    while True:
        try:
            with urllib.request.urlopen(
                health_url,
                timeout=15
            ) as response:

                if response.status != 200:
                    print(
                        f"SELF-PING: HTTP {response.status}"
                    )

        except Exception as e:
            print(
                f"SELF-PING ERROR: {type(e).__name__}: {e}"
            )

        time.sleep(SELF_PING_INTERVAL)


if SELF_PING_ENABLED:
    threading.Thread(
        target=self_ping,
        daemon=True,
        name="self-ping"
    ).start()


# ============================================================
# TELEGRAM BOT
# ============================================================

def _start_bot():
    asyncio.run(run_bot())


threading.Thread(
    target=_start_bot,
    daemon=True,
    name="telegram-bot"
).start()
