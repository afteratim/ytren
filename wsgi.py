import asyncio
import os
import threading
import time
import urllib.request

from flask import Flask, jsonify

from bot import run_bot

from config import (
    SELF_PING_ENABLED,
    SELF_PING_INTERVAL,
)


# ============================================================
# FLASK
# ============================================================

app = Flask(__name__)


# ============================================================
# HOME
# ============================================================

@app.get("/")
def index():

    return "YouTube Audio Bot is running."


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return jsonify({
        "status": "ok"
    })


# ============================================================
# SELF PING
# ============================================================

def self_ping():

    if not SELF_PING_ENABLED:
        return

    service_url = os.getenv(
        "RENDER_EXTERNAL_URL",
        ""
    ).strip()

    if not service_url:

        print(
            "SELF-PING: "
            "RENDER_EXTERNAL_URL not available."
        )

        return

    health_url = (
        service_url.rstrip("/")
        + "/health"
    )

    # Wait for Gunicorn/Flask.
    time.sleep(30)

    while True:

        try:

            request = urllib.request.Request(
                health_url,
                headers={
                    "User-Agent":
                    "YouTubeAudioBot-SelfPing/1.0"
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=15
            ) as response:

                if response.status != 200:

                    print(
                        f"SELF-PING: "
                        f"HTTP {response.status}"
                    )

        except Exception as exc:

            print(
                f"SELF-PING ERROR: "
                f"{type(exc).__name__}: {exc}"
            )

        time.sleep(
            SELF_PING_INTERVAL
        )


# ============================================================
# START SELF PING
# ============================================================

if SELF_PING_ENABLED:

    threading.Thread(
        target=self_ping,
        daemon=True,
        name="self-ping"
    ).start()


# ============================================================
# START TELEGRAM BOT
# ============================================================

def _start_bot():

    try:

        asyncio.run(
            run_bot()
        )

    except Exception as exc:

        print(
            f"TELEGRAM BOT ERROR: "
            f"{type(exc).__name__}: {exc}"
        )

        raise


threading.Thread(
    target=_start_bot,
    daemon=True,
    name="telegram-bot"
).start()
