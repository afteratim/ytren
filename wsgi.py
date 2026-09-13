import asyncio
import threading
from flask import Flask, jsonify
from bot import run_bot

app = Flask(__name__)

@app.get("/")
def index():
    return "YouTube Audio Bot is running."

@app.get("/health")
def health():
    return jsonify({"status": "ok"})

def _start():
    asyncio.run(run_bot())

threading.Thread(target=_start, daemon=True).start()
