import re
from pathlib import Path
from config import MAX_FILENAME_LEN

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

def safe_filename(name: str, fallback="audio"):
    name = (name or fallback).strip()
    name = INVALID.sub(" - ", name)
    name = re.sub(r"\s+", " ", name)
    name = name.strip(" .")
    if not name:
        name = fallback

    stem_upper = Path(name).stem.upper()
    if stem_upper in RESERVED:
        name = f"_{name}"

    if len(name) > MAX_FILENAME_LEN:
        p = Path(name)
        suffix = p.suffix
        stem = p.stem[:MAX_FILENAME_LEN - len(suffix)]
        name = stem.rstrip(" .") + suffix

    return name

def unique_path(directory: Path, filename: str):
    path = directory / filename
    if not path.exists():
        return path

    p = Path(filename)
    for i in range(2, 10000):
        candidate = directory / f"{p.stem} ({i}){p.suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not create a unique filename.")
