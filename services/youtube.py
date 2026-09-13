import asyncio
import json
import os
from pathlib import Path
import yt_dlp

class DownloadCancelled(Exception):
    pass

class YoutubeService:
    def __init__(self, download_dir: Path):
        self.download_dir = download_dir

    def _cookie_file(self, user_id):
        p = Path(os.getenv("COOKIE_DIR", "/tmp/ytaudio_cookies")) / str(user_id) / "cookies.txt"
        return p if p.exists() else None

    def _base_opts(self, user_id, outtmpl):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": False,
            "ignoreerrors": False,
            "restrictfilenames": False,
            "outtmpl": outtmpl,
            # Best available audio; do not force a codec/container.
            "format": "bestaudio/best",
            "overwrites": True,
            "continuedl": True,
        }
        cookie = self._cookie_file(user_id)
        if cookie:
            opts["cookiefile"] = str(cookie)
        return opts

    async def get_info(self, url, user_id):
        def work():
            opts = self._base_opts(user_id, "%(title)s.%(ext)s")
            opts["skip_download"] = True
            opts["extract_flat"] = False
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        return await asyncio.to_thread(work)

    async def download_video(self, url, user_id, output_dir, playlist_index, title_hint, progress_cb, cancel_event):
        output_dir.mkdir(parents=True, exist_ok=True)
        marker = f"{playlist_index:02d} - " if playlist_index else ""

        # Use yt-dlp's title/ext placeholders. We sanitize the final name afterwards.
        outtmpl = str(output_dir / "%(title)s.%(ext)s")
        cookie = self._cookie_file(user_id)

        def hook(d):
            if cancel_event.is_set():
                raise DownloadCancelled()
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes", 0)
                percent = (done * 100 / total) if total else 0
                progress_cb(percent, done, total, d.get("speed"), d.get("eta"))
            elif d.get("status") == "finished":
                progress_cb(100, d.get("total_bytes", 0), d.get("total_bytes", 0), None, 0)

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": "bestaudio/best",
            "outtmpl": outtmpl,
            "progress_hooks": [hook],
            "continuedl": True,
            "overwrites": True,
            "noplaylist": True,
        }
        if cookie:
            opts["cookiefile"] = str(cookie)

        def work():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                requested = Path(ydl.prepare_filename(info))
                return info, requested

        info, requested = await asyncio.to_thread(work)

        if cancel_event.is_set():
            raise DownloadCancelled()

        if not requested.exists():
            # yt-dlp can change extension after postprocessing.
            candidates = list(output_dir.glob("*"))
            candidates = [p for p in candidates if p.is_file()]
            if not candidates:
                raise FileNotFoundError("yt-dlp completed but no audio file was found.")
            requested = max(candidates, key=lambda p: p.stat().st_mtime)

        from utils.files import safe_filename
        final_name = safe_filename(f"{marker}{title_hint or info.get('title') or requested.stem}{requested.suffix}")
        final = output_dir / final_name
        if requested.resolve() != final.resolve():
            if final.exists():
                final.unlink()
            requested.rename(final)

        return final, info

    async def download_playlist(self, info, user_id, output_dir, worker_submit, cancel_event):
        entries = [e for e in (info.get("entries") or []) if e]
        total = len(entries)
        results = []

        for index, entry in enumerate(entries, 1):
            if cancel_event.is_set():
                break
            url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
            title = entry.get("title") or f"Audio {index:02d}"
            result = await worker_submit(url, index, total, title)
            results.append(result)

        return results
