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
    # COMMON OPTIONS
    # ========================================================

    def _base_opts(
        self,
        user_id,
        outtmpl,
        player_clients=None,
        use_cookie=True,
    ):

        opts = {
            "quiet": True,
            "no_warnings": False,
            "noprogress": True,

            "ignoreerrors": False,

            "restrictfilenames": False,

            "outtmpl": outtmpl,

            # Do not convert to MP3.
            # Download the best audio yt-dlp can expose.
            "format": "bestaudio/best",

            "continuedl": True,
            "overwrites": True,
        }

        # ----------------------------------------------------
        # COOKIE
        # ----------------------------------------------------

        if use_cookie:

            cookie = self._cookie_file(user_id)

            if cookie:
                opts["cookiefile"] = str(cookie)

        # ----------------------------------------------------
        # EXTRACTOR ARGS
        # ----------------------------------------------------

        extractor_args = {}

        # Do NOT force mweb globally anymore.
        #
        # When player_clients is None, yt-dlp decides which
        # clients are appropriate.
        if player_clients:

            extractor_args["youtube"] = {
                "player_client": player_clients,
            }

        # PO provider.
        #
        # The bgutil HTTP provider normally uses
        # 127.0.0.1:4416 automatically, but we explicitly pass
        # our configured URL so this also works if changed later.
        if POT_PROVIDER_URL:

            extractor_args["youtubepot-bgutilhttp"] = {
                "base_url": [
                    POT_PROVIDER_URL
                ]
            }

        if extractor_args:
            opts["extractor_args"] = extractor_args

        return opts

    # ========================================================
    # EXTRACTION ATTEMPTS
    # ========================================================

    def _attempts(self, user_id):
        """
        Extraction/download fallback order.

        We deliberately do not rely on one YouTube client.

        Attempt 1:
            yt-dlp defaults + cookie if available.

        Attempt 2:
            default + web_embedded + cookie.

        Attempt 3:
            mweb + default + cookie.

        Attempt 4:
            yt-dlp defaults WITHOUT cookie.

        Attempt 5:
            mweb + default WITHOUT cookie.

        This is useful because a cookie can sometimes change
        which YouTube clients yt-dlp selects.
        """

        has_cookie = (
            self._cookie_file(user_id)
            is not None
        )

        attempts = []

        if has_cookie:

            attempts.extend([
                {
                    "name": "default-cookie",
                    "clients": None,
                    "cookie": True,
                },

                {
                    "name": "embedded-cookie",
                    "clients": [
                        "default",
                        "web_embedded",
                    ],
                    "cookie": True,
                },

                {
                    "name": "mweb-cookie",
                    "clients": [
                        "mweb",
                        "default",
                    ],
                    "cookie": True,
                },
            ])

        attempts.extend([
            {
                "name": "default-no-cookie",
                "clients": None,
                "cookie": False,
            },

            {
                "name": "mweb-no-cookie",
                "clients": [
                    "mweb",
                    "default",
                ],
                "cookie": False,
            },
        ])

        return attempts

    # ========================================================
    # CHECK AVAILABLE AUDIO
    # ========================================================

    @staticmethod
    def _has_usable_audio(info):
        """
        Check whether yt-dlp actually returned at least one
        format containing audio.
        """

        if not info:
            return False

        formats = info.get("formats") or []

        for fmt in formats:

            acodec = fmt.get("acodec")

            if acodec and acodec != "none":
                return True

        return False

    # ========================================================
    # GET INFO
    # ========================================================

    async def get_info(
        self,
        url,
        user_id
    ):

        errors = []

        attempts = self._attempts(
            user_id
        )

        for attempt in attempts:

            def work():

                opts = self._base_opts(
                    user_id=user_id,
                    outtmpl="%(title)s.%(ext)s",
                    player_clients=attempt["clients"],
                    use_cookie=attempt["cookie"],
                )

                opts.update({
                    "skip_download": True,
                    "extract_flat": False,
                    "noplaylist": False,
                })

                with yt_dlp.YoutubeDL(
                    opts
                ) as ydl:

                    return ydl.extract_info(
                        url,
                        download=False
                    )

            try:

                info = await asyncio.to_thread(
                    work
                )

                if not info:
                    raise RuntimeError(
                        "YouTube returned no information."
                    )

                # Playlist itself does not necessarily have
                # formats. Its entries do.
                if info.get("_type") in (
                    "playlist",
                    "multi_video",
                ):
                    return info

                if info.get("entries"):
                    return info

                if self._has_usable_audio(info):
                    return info

                errors.append(
                    f"{attempt['name']}: "
                    f"no usable audio formats"
                )

            except Exception as exc:

                errors.append(
                    f"{attempt['name']}: "
                    f"{type(exc).__name__}: {exc}"
                )

        # Keep Telegram error reasonably small.
        detail = "\n".join(
            errors[-5:]
        )

        raise RuntimeError(
            "YouTube did not return a usable audio format "
            "after all fallback attempts.\n\n"
            + detail
        )

    # ========================================================
    # DOWNLOAD ONE VIDEO
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

        output_dir = Path(
            output_dir
        )

        output_dir.mkdir(
            parents=True,
            exist_ok=True
        )

        marker = (
            f"{playlist_index:02d} - "
            if playlist_index
            else ""
        )

        errors = []

        attempts = self._attempts(
            user_id
        )

        # ====================================================
        # PROGRESS HOOK
        # ====================================================

        def hook(d):

            if cancel_event.is_set():
                raise DownloadCancelled()

            status = d.get(
                "status"
            )

            if status == "downloading":

                total = (
                    d.get("total_bytes")
                    or
                    d.get(
                        "total_bytes_estimate"
                    )
                    or 0
                )

                done = d.get(
                    "downloaded_bytes",
                    0
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
                    d.get("total_bytes")
                    or
                    d.get(
                        "downloaded_bytes",
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
        # TRY EACH YOUTUBE CLIENT STRATEGY
        # ====================================================

        for attempt in attempts:

            if cancel_event.is_set():
                raise DownloadCancelled()

            # Unique temporary template for each attempt.
            #
            # This prevents a failed attempt from being confused
            # with the successful file from another attempt.
            attempt_template = str(
                output_dir
                / (
                    f".yt-{attempt['name']}-"
                    "%(id)s.%(ext)s"
                )
            )

            def work():

                opts = self._base_opts(
                    user_id=user_id,
                    outtmpl=attempt_template,
                    player_clients=attempt["clients"],
                    use_cookie=attempt["cookie"],
                )

                opts.update({
                    "noplaylist": True,
                    "progress_hooks": [
                        hook
                    ],
                })

                with yt_dlp.YoutubeDL(
                    opts
                ) as ydl:

                    info = ydl.extract_info(
                        url,
                        download=True
                    )

                    if not info:
                        raise RuntimeError(
                            "YouTube returned no video information."
                        )

                    requested = Path(
                        ydl.prepare_filename(
                            info
                        )
                    )

                    return (
                        info,
                        requested
                    )

            try:

                info, requested = (
                    await asyncio.to_thread(
                        work
                    )
                )

                if cancel_event.is_set():
                    raise DownloadCancelled()

                # --------------------------------------------
                # LOCATE ACTUAL DOWNLOADED FILE
                # --------------------------------------------

                if not requested.exists():

                    video_id = (
                        info.get("id")
                        or ""
                    )

                    candidates = [
                        p
                        for p in output_dir.glob(
                            f".yt-{attempt['name']}-{video_id}.*"
                        )
                        if (
                            p.is_file()
                            and
                            not p.name.endswith(
                                ".part"
                            )
                        )
                    ]

                    if not candidates:

                        raise FileNotFoundError(
                            "yt-dlp reported completion "
                            "but the audio file was not found."
                        )

                    requested = max(
                        candidates,
                        key=lambda p:
                        p.stat().st_mtime
                    )

                # --------------------------------------------
                # FINAL FILENAME
                # --------------------------------------------

                from utils.files import (
                    safe_filename,
                    unique_path,
                )

                title = (
                    title_hint
                    or
                    info.get("title")
                    or
                    requested.stem
                )

                final_name = safe_filename(
                    f"{marker}"
                    f"{title}"
                    f"{requested.suffix}"
                )

                final = unique_path(
                    output_dir
                    / final_name
                )

                if (
                    requested.resolve()
                    !=
                    final.resolve()
                ):

                    requested.rename(
                        final
                    )

                return (
                    final,
                    info
                )

            except DownloadCancelled:
                raise

            except Exception as exc:

                errors.append(
                    f"{attempt['name']}: "
                    f"{type(exc).__name__}: {exc}"
                )

                # Clean only temporary files belonging to
                # this failed attempt.
                for temp in output_dir.glob(
                    f".yt-{attempt['name']}-*"
                ):

                    try:

                        if temp.is_file():
                            temp.unlink()

                    except OSError:
                        pass

        # ====================================================
        # ALL ATTEMPTS FAILED
        # ====================================================

        detail = "\n".join(
            errors[-5:]
        )

        raise RuntimeError(
            "All YouTube audio download methods failed.\n\n"
            + detail
        )

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

        total = len(
            entries
        )

        for index, entry in enumerate(
            entries,
            1
        ):

            if cancel_event.is_set():
                break

            url = (
                entry.get(
                    "webpage_url"
                )
                or
                entry.get(
                    "original_url"
                )
                or
                entry.get("url")
            )

            title = (
                entry.get("title")
                or
                f"Audio {index:02d}"
            )

            result = await worker_submit(
                url,
                index,
                total,
                title
            )

            results.append(
                result
            )

        return results
