import asyncio
import os
from pathlib import Path

import yt_dlp

from config import POT_PROVIDER_URL


class DownloadCancelled(Exception):
    pass


class YoutubeService:

    def __init__(self, download_dir: Path):
        self.download_dir = Path(download_dir)

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

        if path.exists() and path.is_file():
            return path

        return None

    # ========================================================
    # BASIC OPTIONS
    # ========================================================

    def _common_opts(
        self,
        user_id,
        outtmpl,
        use_cookie=True,
    ):
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,

            "outtmpl": str(outtmpl),

            "continuedl": True,
            "overwrites": True,

            # Do not convert audio.
            # Download best audio format yt-dlp can access.
            "format": "bestaudio/best",
        }

        if use_cookie:
            cookie = self._cookie_file(user_id)

            if cookie:
                opts["cookiefile"] = str(cookie)

        return opts

    # ========================================================
    # EXTRACTION STRATEGIES
    # ========================================================

    def _strategies(self, user_id):
        """
        Return extraction strategies in retry order.

        We deliberately do NOT force mweb for every request.

        Strategy order:

        1. yt-dlp defaults
        2. default + mweb with PO provider
        3. mweb + default with PO provider
        4. web_embedded fallback
        5. android_vr fallback

        Cookies are used automatically when the user has
        uploaded them.
        """

        return [

            # ------------------------------------------------
            # 1. NORMAL YT-DLP
            # ------------------------------------------------
            {
                "name": "default",
                "extractor_args": None,
            },

            # ------------------------------------------------
            # 2. DEFAULT + MWEB
            # ------------------------------------------------
            {
                "name": "default+mweb",
                "extractor_args": {
                    "youtube": {
                        "player_client": [
                            "default",
                            "mweb",
                        ],
                    },

                    "youtubepot-bgutilhttp": {
                        "base_url": [
                            POT_PROVIDER_URL
                        ],
                    },
                },
            },

            # ------------------------------------------------
            # 3. MWEB FIRST
            # ------------------------------------------------
            {
                "name": "mweb+default",
                "extractor_args": {
                    "youtube": {
                        "player_client": [
                            "mweb",
                            "default",
                        ],
                    },

                    "youtubepot-bgutilhttp": {
                        "base_url": [
                            POT_PROVIDER_URL
                        ],
                    },
                },
            },

            # ------------------------------------------------
            # 4. WEB EMBEDDED
            # ------------------------------------------------
            {
                "name": "web_embedded",
                "extractor_args": {
                    "youtube": {
                        "player_client": [
                            "web_embedded",
                        ],
                    },
                },
            },

            # ------------------------------------------------
            # 5. ANDROID VR
            # ------------------------------------------------
            {
                "name": "android_vr",
                "extractor_args": {
                    "youtube": {
                        "player_client": [
                            "android_vr",
                        ],
                    },
                },
            },
        ]

    # ========================================================
    # APPLY STRATEGY
    # ========================================================

    def _apply_strategy(
        self,
        opts,
        strategy,
    ):
        extractor_args = strategy.get(
            "extractor_args"
        )

        if extractor_args:
            opts["extractor_args"] = extractor_args

        return opts

    # ========================================================
    # CHECK WHETHER INFO HAS FORMATS
    # ========================================================

    def _has_formats(self, info):
        if not info:
            return False

        formats = info.get("formats") or []

        if formats:
            return True

        # Playlist itself does not necessarily contain formats.
        if info.get("_type") in (
            "playlist",
            "multi_video",
        ):
            return True

        return False

    # ========================================================
    # GET INFO
    # ========================================================

    async def get_info(
        self,
        url,
        user_id,
    ):
        """
        Extract metadata using several YouTube client
        strategies.

        This avoids failing immediately just because one
        client exposes no downloadable formats.
        """

        def work():

            errors = []

            for strategy in self._strategies(user_id):

                name = strategy["name"]

                opts = self._common_opts(
                    user_id=user_id,
                    outtmpl="%(title)s.%(ext)s",
                )

                opts.update({
                    "skip_download": True,
                    "extract_flat": False,
                    "noplaylist": False,
                })

                self._apply_strategy(
                    opts,
                    strategy,
                )

                try:

                    with yt_dlp.YoutubeDL(opts) as ydl:

                        info = ydl.extract_info(
                            url,
                            download=False,
                        )

                    if self._has_formats(info):
                        return info

                    errors.append(
                        f"{name}: no formats"
                    )

                except Exception as exc:

                    errors.append(
                        f"{name}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

            # -----------------------------------------------
            # ALL STRATEGIES FAILED
            # -----------------------------------------------

            short_errors = "\n".join(
                errors[-5:]
            )

            raise RuntimeError(
                "YouTube extraction failed with all "
                "available clients.\n\n"
                + short_errors
            )

        return await asyncio.to_thread(work)

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
        cancel_event,
    ):

        output_dir = Path(output_dir)

        output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        marker = (
            f"{playlist_index:02d} - "
            if playlist_index
            else ""
        )

        # Each retry needs a predictable template.
        outtmpl = str(
            output_dir
            / "%(title)s.%(ext)s"
        )

        # ====================================================
        # PROGRESS HOOK
        # ====================================================

        def hook(d):

            if cancel_event.is_set():
                raise DownloadCancelled()

            status = d.get("status")

            if status == "downloading":

                total = (
                    d.get("total_bytes")
                    or d.get(
                        "total_bytes_estimate"
                    )
                    or 0
                )

                done = (
                    d.get(
                        "downloaded_bytes",
                        0
                    )
                    or 0
                )

                if total:
                    percent = (
                        done * 100 / total
                    )
                else:
                    percent = 0

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
                    or d.get(
                        "total_bytes_estimate"
                    )
                    or d.get(
                        "downloaded_bytes"
                    )
                    or 0
                )

                progress_cb(
                    100,
                    total,
                    total,
                    None,
                    0,
                )

        # ====================================================
        # DOWNLOAD WORKER
        # ====================================================

        def work():

            errors = []

            for strategy in self._strategies(user_id):

                if cancel_event.is_set():
                    raise DownloadCancelled()

                name = strategy["name"]

                opts = self._common_opts(
                    user_id=user_id,
                    outtmpl=outtmpl,
                )

                opts.update({
                    "noplaylist": True,
                    "progress_hooks": [
                        hook
                    ],
                })

                self._apply_strategy(
                    opts,
                    strategy,
                )

                try:

                    with yt_dlp.YoutubeDL(opts) as ydl:

                        # First inspect the formats.
                        info = ydl.extract_info(
                            url,
                            download=False,
                        )

                        if not self._has_formats(info):

                            errors.append(
                                f"{name}: "
                                "no downloadable formats"
                            )

                            continue

                        if cancel_event.is_set():
                            raise DownloadCancelled()

                        # Now download using the SAME
                        # extraction strategy.
                        info = ydl.extract_info(
                            url,
                            download=True,
                        )

                        requested = Path(
                            ydl.prepare_filename(
                                info
                            )
                        )

                        return (
                            info,
                            requested,
                            name,
                        )

                except DownloadCancelled:
                    raise

                except Exception as exc:

                    errors.append(
                        f"{name}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

            # -----------------------------------------------
            # EVERYTHING FAILED
            # -----------------------------------------------

            short_errors = "\n".join(
                errors[-5:]
            )

            raise RuntimeError(
                "All YouTube download methods failed."
                "\n\n"
                + short_errors
            )

        info, requested, strategy_name = (
            await asyncio.to_thread(work)
        )

        # ====================================================
        # CANCEL CHECK
        # ====================================================

        if cancel_event.is_set():
            raise DownloadCancelled()

        # ====================================================
        # LOCATE DOWNLOADED FILE
        # ====================================================

        if not requested.exists():

            candidates = [
                p
                for p in output_dir.iterdir()
                if p.is_file()
                and not p.name.endswith(
                    ".part"
                )
            ]

            if not candidates:

                raise FileNotFoundError(
                    "yt-dlp reported success but "
                    "the downloaded audio file "
                    "could not be found."
                )

            requested = max(
                candidates,
                key=lambda p: (
                    p.stat().st_mtime
                ),
            )

        # ====================================================
        # FINAL SAFE FILENAME
        # ====================================================

        from utils.files import safe_filename

        title = (
            title_hint
            or info.get("title")
            or requested.stem
        )

        final_name = safe_filename(
            f"{marker}"
            f"{title}"
            f"{requested.suffix}"
        )

        final = (
            output_dir
            / final_name
        )

        # ====================================================
        # DUPLICATE PROTECTION
        # ====================================================

        if (
            requested.resolve()
            != final.resolve()
        ):

            if final.exists():

                base = final.stem
                suffix = final.suffix

                number = 2

                while True:

                    candidate = (
                        output_dir
                        / safe_filename(
                            f"{base} ({number})"
                            f"{suffix}"
                        )
                    )

                    if not candidate.exists():
                        final = candidate
                        break

                    number += 1

            requested.rename(final)

        return final, info

    # ========================================================
    # PLAYLIST
    # ========================================================

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
            for entry in (
                info.get("entries")
                or []
            )
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

            if not url:
                continue

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
