import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# HELPERS
# ============================================================

def _int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def _csv_ints(name: str) -> set[int]:
    value = os.getenv(name, "").strip()

    if not value:
        return set()

    result = set()

    for part in value.split(","):
        part = part.strip()

        if not part:
            continue

        try:
            result.add(int(part))
        except ValueError:
            continue

    return result


# ============================================================
# TELEGRAM BOT
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

API_ID = _int("API_ID", 0)

API_HASH = os.getenv("API_HASH", "").strip()

OWNER_ID = _int("OWNER_ID", 0)

ALLOWED_USERS = _csv_ints("ALLOWED_USERS")

# Owner is always allowed.
if OWNER_ID:
    ALLOWED_USERS.add(OWNER_ID)

DUMP_CHANNEL_ID = _int("DUMP_CHANNEL_ID", 0)


# ============================================================
# DIRECTORIES
# ============================================================

DOWNLOAD_DIR = Path(
    os.getenv(
        "DOWNLOAD_DIR",
        "/tmp/ytaudio_downloads"
    )
)

COOKIE_DIR = Path(
    os.getenv(
        "COOKIE_DIR",
        "/tmp/ytaudio_cookies"
    )
)


# Create directories if they do not exist.
DOWNLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)

COOKIE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# DOWNLOAD SETTINGS
# ============================================================

# Maximum number of videos downloading at the same time.
MAX_CONCURRENT = max(
    1,
    _int("MAX_CONCURRENT", 2)
)


# ============================================================
# JOB TIMEOUT
# ============================================================

# Maximum lifetime of one overall download job.
#
# 21600 seconds = 6 hours.
#
# This is NOT the maximum video length or file size.
# It is simply a safety timeout for a stuck job.
JOB_TIMEOUT = max(
    60,
    _int("JOB_TIMEOUT", 21600)
)


# ============================================================
# LARGE FILE SPLITTING
# ============================================================

# Telegram upload splitting threshold.
#
# 1.9 GB in binary GiB units.
SPLIT_SIZE_GB = float(
    os.getenv(
        "SPLIT_SIZE_GB",
        "1.9"
    )
)

SPLIT_SIZE_BYTES = int(
    SPLIT_SIZE_GB * 1024 * 1024 * 1024
)


# ============================================================
# FILENAMES
# ============================================================

MAX_FILENAME_LEN = max(
    50,
    _int("MAX_FILENAME_LEN", 180)
)


# ============================================================
# SELF PING
# ============================================================

SELF_PING_ENABLED = os.getenv(
    "SELF_PING_ENABLED",
    "true"
).lower() in (
    "1",
    "true",
    "yes",
    "on"
)


# Ping interval in seconds.
#
# 600 seconds = 10 minutes.
SELF_PING_INTERVAL = max(
    60,
    _int(
        "SELF_PING_INTERVAL",
        60
    )
)
