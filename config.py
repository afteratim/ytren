import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _int(name, default=0):
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default

def _float(name, default):
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_ID = _int("API_ID")
API_HASH = os.getenv("API_HASH", "").strip()

OWNER_ID = _int("OWNER_ID")
ALLOWED_USERS = {
    int(x.strip())
    for x in os.getenv("ALLOWED_USERS", "").split(",")
    if x.strip().lstrip("-").isdigit()
}
if OWNER_ID:
    ALLOWED_USERS.add(OWNER_ID)

DUMP_CHANNEL_ID = os.getenv("DUMP_CHANNEL_ID", "").strip()

DOWNLOAD_DIR = Path(os.getenv("DOWNLOAD_DIR", "/tmp/ytaudio_downloads"))
COOKIE_DIR = Path(os.getenv("COOKIE_DIR", "/tmp/ytaudio_cookies"))

MAX_CONCURRENT = max(1, _int("MAX_CONCURRENT", 2))
SPLIT_SIZE_GB = max(0.1, _float("SPLIT_SIZE_GB", 1.9))
SPLIT_SIZE_BYTES = int(SPLIT_SIZE_GB * 1024**3)

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
COOKIE_DIR.mkdir(parents=True, exist_ok=True)

MAX_FILENAME_LEN = 180
