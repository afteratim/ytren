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

    # =========================================================
    # COOKIE FILE
    # =========================================================

    def _cookie_file(self, user_id):
        cookie_path = (
            Path(
                os.getenv(
                    "COOKIE_DIR",
                    "/tmp/ytaudio_cookies",
                )
            )
            / str(user_id)
            / "cookies.txt"
        )

        if cookie_path.exists() and cookie_path.is_file():
            return cookie_path

        return None

    # =========================================================
    # YOUTUBE EXTRACTOR ARGUMENTS
    # =========================================================

    def _youtube_extractor_args(self):
        """
        Current YouTube client configuration.

        mweb:
            Primary client used with the bgutil PO-token provider.

        web_embedded:
            Fallback for videos that support the embedded player.

        default:
            Additional fallback.
        """

        return {
            "youtube": {
                "player_client": [
                    "mweb",
                    "web_embedded",
                    "default",
                ]
            }
        }

    # =========================================================
    # COMMON YT-DLP OPTIONS
    # =========================================================

    def _base_opts(
        self,
        user_id,
        outtmpl,
        skip_download=False,
    ):
        opts = {
            # -------------------------------------------------
            # General
            # -------------------------------------------------

            "quiet": True,
            "no_warnings": True,
            "noprogress": True,

            # -------------------------------------------------
            # BEST AVAILABLE AUDIO
            # -------------------------------------------------
            #
            # Prefer a normal HTTP audio stream.
            #
            # Do NOT force MP3 conversion.
            #

            "format": (
                "(bestaudio)[protocol^=http]/"
                "bestaudio/"
                "best"
            ),

            # -------------------------------------------------
            # No conversion
            # -------------------------------------------------

            "postprocessors": [],

            # -------------------------------------------------
            # Output
            # -------------------------------------------------

            "outtmpl": outtmpl,
            "restrictfilenames": False,
            "overwrites": True,
            "continuedl": True,

            # -------------------------------------------------
            # Playlist
            # -------------------------------------------------

            "noplaylist": False,
            "ignoreerrors": False,

            # -------------------------------------------------
            # JavaScript runtime
            # -------------------------------------------------

            "js_runtimes": {
                "node": {}
            },

            # -------------------------------------------------
            # YouTube extractor
            # -------------------------------------------------

            "extractor_args": self._youtube_extractor_args(),

            # -------------------------------------------------
            # EJS
            # -------------------------------------------------

            "remote_components": {
                "ejs:github"
            },

            # -------------------------------------------------
            # Network
            # -------------------------------------------------

            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,

            "skip_unavailable_fragments": True,
        }

        # =====================================================
        # BGUTIL PO TOKEN PROVIDER
        # =====================================================

        opts["extractor_args"][
            "youtubepot-bgutilhttp"
        ] = {
            "base_url": POT_PROVIDER_URL
        }

        # =====================================================
        # COOKIE
        # =====================================================

        cookie = self._cookie_file(user_id)

        if cookie:
            opts["cookiefile"] = str(cookie)

        # =====================================================
        # METADATA ONLY
        # =====================================================

        if skip_download:
            opts["skip_download"] = True
            opts["extract_flat"] = False

        return opts

    # =========================================================
    # GET VIDEO / PLAYLIST INFORMATION
    # =========================================================

    async def get_info(
        self,
        url,
        user_id,
    ):
        """
        Extract YouTube information without downloading.
        """

        def work():

            opts = self._base_opts(
                user_id=user_id,
                outtmpl="%(title)s.%(ext)s",
                skip_download=True,
            )

            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(
                    url,
                    download=False,
                )

        return await asyncio.to_thread(work)

    # =========================================================
    # DOWNLOAD ONE VIDEO
    # =========================================================

    async def download_video(
        self,
        url,
        user_id,
        output_dir,
        playlist_index,
        title_hint,
        progress_cb,
        cancel_event,
    ):
        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        # =====================================================
        # PLAYLIST PREFIX
        # =====================================================

        marker = (
            f"{playlist_index:02d} - "
            if playlist_index
            else ""
        )

        # =====================================================
        # TEMPORARY OUTPUT
        # =====================================================

        outtmpl = str(
            output_dir / "%(title)s.%(ext)s"
        )

        # =====================================================
        # PROGRESS HOOK
        # =====================================================

        def hook(data):

            # -------------------------------------------------
            # Cancellation
            # -------------------------------------------------

            if cancel_event.is_set():
                raise DownloadCancelled()

            status = data.get("status")

            # -------------------------------------------------
            # Downloading
            # -------------------------------------------------

            if status == "downloading":

                total = (
                    data.get("total_bytes")
                    or data.get("total_bytes_estimate")
                    or 0
                )

                downloaded = data.get(
                    "downloaded_bytes",
                    0,
                )

                if total:
                    percent = (
                        downloaded * 100 / total
                    )
                else:
                    percent = 0

                progress_cb(
                    percent,
                    downloaded,
                    total,
                    data.get("speed"),
                    data.get("eta"),
                )

            # -------------------------------------------------
            # Finished
            # -------------------------------------------------

            elif status == "finished":

                total = (
                    data.get("total_bytes")
                    or data.get("total_bytes_estimate")
                    or 0
                )

                progress_cb(
                    100,
                    total,
                    total,
                    None,
                    0,
                )

        # =====================================================
        # YT-DLP OPTIONS
        # =====================================================

        opts = self._base_opts(
            user_id=user_id,
            outtmpl=outtmpl,
            skip_download=False,
        )

        # This call downloads ONE video only.
        opts["noplaylist"] = True

        opts["progress_hooks"] = [
            hook
        ]

        # No audio conversion.
        opts["postprocessors"] = []

        # =====================================================
        # DOWNLOAD
        # =====================================================

        def work():

            with yt_dlp.YoutubeDL(opts) as ydl:

                info = ydl.extract_info(
                    url,
                    download=True,
                )

                if not info:
                    raise RuntimeError(
                        "yt-dlp returned no video information."
                    )

                requested = Path(
                    ydl.prepare_filename(info)
                )

                return info, requested

        info, requested = await asyncio.to_thread(
            work
        )

        # =====================================================
        # CANCELLATION CHECK
        # =====================================================

        if cancel_event.is_set():
            raise DownloadCancelled()

        # =====================================================
        # FIND DOWNLOADED FILE
        # =====================================================

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
                key=lambda p: p.stat().st_mtime,
            )

        # =====================================================
        # FINAL FILENAME
        # =====================================================

        from utils.files import safe_filename

        title = (
            title_hint
            or info.get("title")
            or requested.stem
        )

        final_name = safe_filename(
            f"{marker}{title}{requested.suffix}"
        )

        final = output_dir / final_name

        # =====================================================
        # RENAME
        # =====================================================

        if requested.resolve() != final.resolve():

            if final.exists():
                final.unlink()

            requested.rename(final)

        return final, info

    # =========================================================
    # PLAYLIST
    # =========================================================

    async def download_playlist(
        self,
        info,
        user_id,
        output_dir,
        worker_submit,
        cancel_event,
    ):
        """
        Playlist helper.

        Actual concurrent worker management is handled
        by JobManager.
        """

        entries = [
            entry
            for entry in (
                info.get("entries") or []
            )
            if entry
        ]

        results = []

        total = len(entries)

        for index, entry in enumerate(
            entries,
            1,
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
                total,
                title,
            )

            results.append(result)

        return results
