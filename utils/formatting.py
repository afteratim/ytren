import time

def human_bytes(n):
    n = float(max(0, n))
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if n < 1024 or unit == units[-1]:
            return f"{n:.1f} {unit}"
        n /= 1024

def human_time(seconds):
    if seconds is None or seconds < 0:
        return "—"
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def progress_bar(percent, width=16):
    p = max(0, min(100, percent))
    filled = int(width * p / 100)
    return "█" * filled + "░" * (width - filled)

def speed_text(bytes_done, elapsed):
    if elapsed <= 0:
        return "—"
    return human_bytes(bytes_done / elapsed) + "/s"
