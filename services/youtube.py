import asyncio
import os
from pathlib import Path

import yt_dlp

from config import POT_PROVIDER_URL


class DownloadCancelled(Exception):
    pass


class YoutubeService:

    def __init__(self, download_dir: Path):
        self.download_dir = download_dir

    # ========================================================
    # COOKIE
    # ========================================================

    def _cookie_file(self, user_id):
        cookie_dir = Path(
            os.getenv(
                "COOKIE_DIR",
                "/tmp/ytaudio_cookies"
            )
        )

        path = (
            cookie_dir
            / str(user_id)
            / "cookies.txt"
        )

        return path if path.exists() else None

    # ========================================================
    # COMMON YT-DLP OPTIONS
    # ========================================================

    def _base_opts(self, user_id, outtmpl):

        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,

            "noplaylist": False,

            "ignoreerrors": False,

            "restrictfilenames": False,

            "outtmpl": outtmpl,

            # Best available audio.
            #
            # We deliberately do NOT force MP3/M4A/Opus.
            "format": "bestaudio/best",

            "overwrites": True,

            "continuedl": True,

            # =================================================
            # PO TOKEN PROVIDER
            # =================================================
            #
            # YouTube's current PO-token guidance recommends
            # using a provider with the mweb client.
            "extractor_args": {
                "youtube": {
                    "player_client": [
                        "mweb"
                    ]
                },

                "youtubepot-bgutilhttp": {
                    "base_url": [
                        POT_PROVIDER_URL
                    ]
                }
            }
        }

        cookie = self._cookie_file(user_id)

        if cookie:
            opts["cookiefile"] = str(cookie)

        return opts

    # ========================================================
    # GET INFO
    # ========================================================

    async def get_info(
        self,
        url,
        user_id
    ):

        def work():

            opts = self._base_opts(
                user_id,
                "%(title)s.%(ext)s"
            )

            opts["skip_download"] = True

            opts["extract_flat"] = False

            with yt_dlp.YoutubeDL(opts) as ydl:

                return ydl.extract_info(
                    url,
                    download=False
                )

        return await asyncio.to_thread(
            work
        )

    # ========================================================
    # DOWNLOAD VIDEO
    # ========================================================

    async def download_video(
        self,
        url,
        user_id,
        output_dir,
        playlist_index,
        title_hint,
        progress_cb,
        cancel_event
    ):

        output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        marker = (
            f"{playlist_index:02d} - "
            if playlist_index
            else ""
        )

        outtmpl = str(
            output_dir
            / "%(title)s.%(ext)s"
        )

        # ====================================================
        # PROGRESS HOOK
        # ====================================================

        def hook(d):

            # Cancellation is checked continuously.
            if cancel_event.is_set():
                raise DownloadCancelled()

            status = d.get("status")

            if status == "downloading":

                total = (
                    d.get("total_bytes")
                    or d.get("total_bytes_estimate")
                    or 0
                )

                done = (
                    d.get(
                        "downloaded_bytes",
                        0
                    )
                )

                percent = (
                    done * 100 / total
                    if total
                    else 0
                )

                progress_cb(
                    percent,
                    done,
                    total,
                    d.get("speed"),
                    d.get("eta")
                )

            elif status == "finished":

                total = (
                    d.get(
                        "total_bytes",
                        0
                    )
                )

                progress_cb(
                    100,
                    total,
                    total,
                    None,
                    0
                )

        # ====================================================
        # YT-DLP OPTIONS
        # ====================================================

        opts = self._base_opts(
            user_id,
            outtmpl
        )

        opts.update({
            "noplaylist": True,
            "progress_hooks": [hook],
        })

        # ====================================================
        # DOWNLOAD
        # ====================================================

        def work():

            with yt_dlp.YoutubeDL(opts) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True
                )

                requested = Path(
                    ydl.prepare_filename(
                        info
                    )
                )

                return info, requested

        info, requested = await asyncio.to_thread(
            work
        )

        # ====================================================
        # CANCEL CHECK
        # ====================================================

        if cancel_event.is_set():
            raise DownloadCancelled()

        # ====================================================
        # FIND FILE
        # ====================================================

        if not requested.exists():

            candidates = [
                p
                for p in output_dir.glob("*")
                if p.is_file()
            ]

            if not candidates:

                raise FileNotFoundError(
                    "yt-dlp completed but no audio file was found."
                )

            requested = max(
                candidates,
                key=lambda p: p.stat().st_mtime
            )

        # ====================================================
        # SAFE FINAL FILENAME
        # ====================================================

        from utils.files import safe_filename

        title = (
            title_hint
            or info.get("title")
            or requested.stem
        )

        final_name = safe_filename(
            f"{marker}{title}{requested.suffix}"
        )

        final = (
            output_dir
            / final_name
        )

        if requested.resolve() != final.resolve():

            if final.exists():
                final.unlink()

            requested.rename(final)

        return final, info

    # ========================================================
    # DOWNLOAD PLAYLIST
    # ========================================================

    async def download_playlist(
        self,
        info,
        user_id,
        output_dir,
        worker_submit,
        cancel_event
    ):

        entries = [
            entry
            for entry in (
                info.get("entries")
                or []
            )
            if entry
        ]

        results = []

        for index, entry in enumerate(
            entries,
            1
        ):

            if cancel_event.is_set():
                break

            url = (
                entry.get("webpage_url")
                or entry.get("original_url")
                or entry.get("url")
            )

            title = (
                entry.get("title")
                or f"Audio {index:02d}"
            )

            result = await worker_submit(
                url,
                index,
                len(entries),
                title
            )

            results.append(result)

        return results
