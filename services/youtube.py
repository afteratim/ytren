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

    # ---------------------------------------------------------
    # COOKIE
    # ---------------------------------------------------------

    def _cookie_file(self, user_id):
        path = (
            Path(os.getenv("COOKIE_DIR", "/tmp/ytaudio_cookies"))
            / str(user_id)
            / "cookies.txt"
        )

        return path if path.exists() else None

    # ---------------------------------------------------------
    # COMMON YOUTUBE OPTIONS
    # ---------------------------------------------------------

    def _youtube_extractor_args(self, use_cookie=False):
        """
        Current YouTube extraction strategy.

        We deliberately do NOT use:
            web
            web_creator

        as the only client because current YouTube PO-token/SABR
        changes can leave no downloadable formats.

        mweb is used with the bgutil PO-token provider.
        web_embedded is kept as a fallback for embeddable videos.
        """

        args = {
            "youtube": {
                "player_client": ["mweb", "web_embedded", "default"],
            }
        }

        return args

    def _base_opts(self, user_id, outtmpl, skip_download=False):
        opts = {
            # -------------------------------------------------
            # General
            # -------------------------------------------------
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,

            # -------------------------------------------------
            # Audio
            # -------------------------------------------------
            #
            # Prefer a real HTTP audio stream.
            #
            # The [protocol^=http] condition prevents yt-dlp
            # from selecting a SABR-only format that cannot be
            # downloaded directly.
            #
            "format": (
                "(bestaudio)[protocol^=http]/"
                "bestaudio/"
                "best"
            ),

            # Do NOT convert audio.
            # We want the original/best available container.
            "postprocessors": [],

            # -------------------------------------------------
            # Output
            # -------------------------------------------------
            "outtmpl": outtmpl,
            "restrictfilenames": False,
            "overwrites": True,
            "continuedl": True,

            # -------------------------------------------------
            # YouTube
            # -------------------------------------------------
            "noplaylist": False,
            "ignoreerrors": False,

            # -------------------------------------------------
            # JavaScript
            # -------------------------------------------------
            #
            # Node is installed in our Docker image.
            #
            "js_runtimes": {
                "node": {}
            },

            # -------------------------------------------------
            # PO Token provider
            # -------------------------------------------------
            #
            # bgutil HTTP server is running on localhost:4416.
            #
            "extractor_args": self._youtube_extractor_args(
                use_cookie=use_cookie
            ),

            # -------------------------------------------------
            # EJS / remote components
            # -------------------------------------------------
            #
            # Current yt-dlp can use its EJS solver with a JS
            # runtime. Keeping this enabled improves current
            # YouTube compatibility.
            #
            "remote_components": {
                "ejs:github"
            },

            # -------------------------------------------------
            # Networking
            # -------------------------------------------------
            "socket_timeout": 30,
            "retries": 5,
            "fragment_retries": 5,

            # Don't abort the whole playlist because a single
            # video has an extraction problem.
            "skip_unavailable_fragments": True,
        }

        cookie = self._cookie_file(user_id)

        if cookie:
            opts["cookiefile"] = str(cookie)

        if skip_download:
            opts["skip_download"] = True
            opts["extract_flat"] = False

        return opts

    # ---------------------------------------------------------
    # EXTRACTION
    # ---------------------------------------------------------

    async def get_info(self, url, user_id):
        """
        Extract metadata first.

        We use the same YouTube configuration as the actual
        downloader so that the metadata extraction and download
        don't use completely different clients.
        """

        def work():
            opts = self._base_opts(
                user_id,
                "%(title)s.%(ext)s",
                skip_download=True,
            )

            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(
                    url,
                    download=False,
                )

        return await asyncio.to_thread(work)

    # ---------------------------------------------------------
    # DOWNLOAD ONE VIDEO
    # ---------------------------------------------------------

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

        marker = (
            f"{playlist_index:02d} - "
            if playlist_index
            else ""
        )

        outtmpl = str(
            output_dir / "%(title)s.%(ext)s"
        )

        cookie = self._cookie_file(user_id)

        # -----------------------------------------------------
        # Progress hook
        # -----------------------------------------------------

        def hook(d):
            if cancel_event.is_set():
                raise DownloadCancelled()

            status = d.get("status")

            if status == "downloading":
                total = (
                    d.get("total_bytes")
                    or d.get("total_bytes_estimate")
                    or 0
                )

                done = d.get(
                    "downloaded_bytes",
                    0,
                )

                percent = (
                    (done * 100 / total)
                    if total
                    else 0
                )

                progress_cb(
                    percent,
                    done,
                    total,
                    d.get("speed"),
                    d.get("eta"),
                )

            elif status == "finished":
                total = (
                    d.get("total_bytes")
                    or d.get("total_bytes_estimate")
                    or 0
                )

                progress_cb(
                    100,
                    total,
                    total,
                    None,
                    0,
                )

        # -----------------------------------------------------
        # yt-dlp options
        # -----------------------------------------------------

        opts = self._base_opts(
            user_id,
            outtmpl,
            skip_download=False,
        )

        opts["noplaylist"] = True
        opts["progress_hooks"] = [hook]

        # We don't want yt-dlp to perform arbitrary audio
        # conversion.
        opts["postprocessors"] = []

        # -----------------------------------------------------
        # Download
        # -----------------------------------------------------

        def work():
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    url,
                    download=True,
                )

                requested = Path(
                    ydl.prepare_filename(info)
                )

                return info, requested

        info, requested = await asyncio.to_thread(
            work
        )

        if cancel_event.is_set():
            raise DownloadCancelled()

        # -----------------------------------------------------
        # Find downloaded file
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Final filename
        # -----------------------------------------------------

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

        if requested.resolve() != final.resolve():

            if final.exists():
                final.unlink()

            requested.rename(final)

        return final, info

    # ---------------------------------------------------------
    # PLAYLIST
    # ---------------------------------------------------------

    async def download_playlist(
        self,
        info,
        user_id,
        output_dir,
        worker_submit,
        cancel_event,
    ):
        entries = [
            entry
            for entry in (info.get("entries") or [])
            if entry
        ]

        results = []

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
                len(entries),
                title,
            )

            results.append(result)

        return results
