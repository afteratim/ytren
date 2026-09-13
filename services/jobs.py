import asyncio
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from config import (
    DOWNLOAD_DIR,
    MAX_CONCURRENT,
    JOB_TIMEOUT,
)

from services.youtube import (
    YoutubeService,
    DownloadCancelled,
)

from utils.formatting import (
    human_bytes,
    human_time,
    progress_bar,
)


# ============================================================
# VIDEO CANCEL STATE
# ============================================================

@dataclass
class VideoCancel:
    token: str
    event: asyncio.Event = field(
        default_factory=asyncio.Event
    )

    title: str = ""

    index: int = 0

    message_id: int | None = None

    status: str = "queued"


# ============================================================
# JOB
# ============================================================

@dataclass
class Job:

    id: str

    user_id: int

    chat_id: int

    url: str

    task: asyncio.Task | None = None

    message_id: int | None = None

    status: str = "queued"

    current_title: str = ""

    current_index: int = 0

    playlist_total: int = 0

    playlist_done: int = 0

    # --------------------------------------------------------
    # IMPORTANT
    #
    # Every concurrently running video gets its own entry.
    # --------------------------------------------------------

    active_videos: dict[str, VideoCancel] = field(
        default_factory=dict
    )

    started: float = field(
        default_factory=time.time
    )


# ============================================================
# JOB MANAGER
# ============================================================

class JobManager:

    def __init__(self):

        self.jobs = {}

        self.youtube = YoutubeService(
            DOWNLOAD_DIR
        )

    # ========================================================
    # SUBMIT
    # ========================================================

    async def submit(
        self,
        user_id,
        chat_id,
        url,
        application,
    ):

        job_id = uuid.uuid4().hex[:10]

        job = Job(
            id=job_id,
            user_id=user_id,
            chat_id=chat_id,
            url=url,
        )

        self.jobs[job_id] = job

        msg = await application.bot.send_message(
            chat_id,
            (
                f"🔎 Job `{job_id}` queued...\n\n"
                f"{url}"
            ),
            parse_mode="Markdown",
        )

        job.message_id = msg.message_id

        job.task = asyncio.create_task(
            self._run(
                job,
                application,
            )
        )

        return job_id

    # ========================================================
    # MAIN JOB KEYBOARD
    # ========================================================

    def _keyboard(
        self,
        cancel_key=None,
    ):

        if not cancel_key:
            return None

        return InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "❌ Cancel current video",
                        callback_data=(
                            f"cancel:{cancel_key}"
                        ),
                    )
                ]
            ]
        )

    # ========================================================
    # EDIT JOB MESSAGE
    # ========================================================

    async def _edit(
        self,
        bot,
        job,
        text,
        markup=True,
    ):

        if not job.message_id:
            return

        try:

            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.message_id,
                text=text,
                reply_markup=(
                    self._keyboard(job.id)
                    if markup
                    else None
                ),
            )

        except Exception:
            pass

    # ========================================================
    # EDIT VIDEO MESSAGE
    # ========================================================

    async def _edit_video(
        self,
        bot,
        job,
        video,
        text,
        markup=True,
    ):

        if not video.message_id:
            return

        try:

            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=video.message_id,
                text=text,
                reply_markup=(
                    self._keyboard(
                        f"{job.id}:{video.token}"
                    )
                    if markup
                    else None
                ),
            )

        except Exception:
            pass

    # ========================================================
    # CREATE VIDEO MESSAGE
    # ========================================================

    async def _create_video_message(
        self,
        bot,
        job,
        video,
        text,
    ):

        try:

            message = await bot.send_message(
                chat_id=job.chat_id,
                text=text,
                reply_markup=self._keyboard(
                    f"{job.id}:{video.token}"
                ),
            )

            video.message_id = message.message_id

            return message

        except Exception:
            return None

    # ========================================================
    # RUN JOB
    # ========================================================

    async def _run(
        self,
        job,
        application,
    ):

        bot = application.bot

        workdir = (
            DOWNLOAD_DIR / job.id
        )

        workdir.mkdir(
            parents=True,
            exist_ok=True,
        )

        try:

            # ------------------------------------------------
            # ANALYZING
            # ------------------------------------------------

            job.status = "analyzing"

            await self._edit(
                bot,
                job,
                "🔎 Reading YouTube information...",
                False,
            )

            info = await asyncio.wait_for(
                self.youtube.get_info(
                    job.url,
                    job.user_id,
                ),
                timeout=120,
            )

            # ------------------------------------------------
            # PLAYLIST
            # ------------------------------------------------

            if (
                info.get("_type") == "playlist"
                or info.get("entries") is not None
            ):

                entries = [
                    entry
                    for entry in (
                        info.get("entries") or []
                    )
                    if entry
                ]

                if not entries:
                    raise RuntimeError(
                        "The playlist contains no downloadable videos."
                    )

                job.playlist_total = len(
                    entries
                )

                await self._edit(
                    bot,
                    job,
                    (
                        "📋 Playlist found\n\n"
                        f"Videos: {job.playlist_total}\n"
                        f"Workers: {MAX_CONCURRENT}\n\n"
                        "🎵 Downloading best available audio..."
                    ),
                    False,
                )

                await self._playlist(
                    job,
                    entries,
                    application,
                    workdir,
                )

            # ------------------------------------------------
            # SINGLE VIDEO
            # ------------------------------------------------

            else:

                job.playlist_total = 1

                await self._one_video(
                    job,
                    job.url,
                    0,
                    1,
                    info.get("title")
                    or "audio",
                    application,
                    workdir,
                )

        except DownloadCancelled:

            job.status = "cancelled"

            await self._edit(
                bot,
                job,
                "❌ Current video cancelled.",
                False,
            )

        except asyncio.CancelledError:

            job.status = "cancelled"

            await self._edit(
                bot,
                job,
                "❌ Job stopped.",
                False,
            )

        except Exception as exc:

            job.status = "error"

            await self._edit(
                bot,
                job,
                (
                    "❌ Error\n\n"
                    f"{type(exc).__name__}: "
                    f"{str(exc)[:700]}"
                ),
                False,
            )

        finally:

            job.active_videos.clear()

            shutil.rmtree(
                workdir,
                ignore_errors=True,
            )

            self.jobs.pop(
                job.id,
                None,
            )

    # ========================================================
    # PLAYLIST WORKERS
    # ========================================================

    async def _playlist(
        self,
        job,
        entries,
        application,
        workdir,
    ):

        queue = asyncio.Queue()

        for index, entry in enumerate(
            entries,
            1,
        ):
            await queue.put(
                (
                    index,
                    entry,
                )
            )

        # ----------------------------------------------------
        # WORKER
        # ----------------------------------------------------

        async def worker():

            while True:

                try:

                    index, entry = (
                        queue.get_nowait()
                    )

                except asyncio.QueueEmpty:

                    return

                url = (
                    entry.get("webpage_url")
                    or entry.get("original_url")
                    or entry.get("url")
                )

                title = (
                    entry.get("title")
                    or f"Audio {index:02d}"
                )

                try:

                    await self._one_video(
                        job,
                        url,
                        index,
                        len(entries),
                        title,
                        application,
                        workdir,
                    )

                except DownloadCancelled:

                    # The individual video message has
                    # already been updated by _one_video.

                    pass

                except Exception as exc:

                    # Do not kill other concurrent workers.

                    video_text = (
                        f"⚠️ Failed\n\n"
                        f"{index:02d} - {title}\n\n"
                        f"{type(exc).__name__}: "
                        f"{str(exc)[:400]}"
                    )

                    # We intentionally don't overwrite another
                    # worker's progress message here because
                    # _one_video owns its own message.

                    print(
                        f"PLAYLIST VIDEO ERROR "
                        f"{job.id} "
                        f"{index}: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    )

                finally:

                    job.playlist_done += 1

                    queue.task_done()

        # ----------------------------------------------------
        # START WORKERS
        # ----------------------------------------------------

        worker_count = min(
            MAX_CONCURRENT,
            len(entries),
        )

        workers = [
            asyncio.create_task(
                worker()
            )
            for _ in range(worker_count)
        ]

        await asyncio.gather(
            *workers
        )

        # ----------------------------------------------------
        # PLAYLIST COMPLETE
        # ----------------------------------------------------

        await self._edit(
            application.bot,
            job,
            (
                "✅ Playlist completed\n\n"
                f"Completed/processed: "
                f"{job.playlist_done}/"
                f"{job.playlist_total}"
            ),
            False,
        )

    # ========================================================
    # ONE VIDEO
    # ========================================================

    async def _one_video(
        self,
        job,
        url,
        idx,
        total,
        title,
        application,
        workdir,
    ):

        # ====================================================
        # CREATE INDEPENDENT VIDEO STATE
        # ====================================================

        video = VideoCancel(
            token=uuid.uuid4().hex[:8],
            title=title,
            index=idx,
            status="downloading",
        )

        job.active_videos[
            video.token
        ] = video

        job.current_title = title

        job.current_index = idx

        # ====================================================
        # VIDEO DIRECTORY
        # ====================================================

        if total > 1:

            video_dir = (
                workdir
                / f"{idx:04d}"
            )

        else:

            video_dir = (
                workdir
                / "single"
            )

        video_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        job.status = (
            f"downloading {idx}/{total}"
            if total > 1
            else "downloading"
        )

        # ====================================================
        # VIDEO MESSAGE
        # ====================================================

        initial_text = (
            "🎵 Downloading\n\n"
            f"{idx:02d} - {title}"
            if total > 1
            else
            "🎵 Downloading\n\n"
            f"{title}"
        )

        await self._create_video_message(
            application.bot,
            job,
            video,
            initial_text,
        )

        # ====================================================
        # PROGRESS UPDATE CONTROL
        # ====================================================

        last_update = [
            0.0
        ]

        # ====================================================
        # IMPORTANT:
        #
        # Capture the main asyncio event loop.
        #
        # yt-dlp runs in asyncio.to_thread(), therefore its
        # progress hook runs in a worker thread.
        #
        # asyncio.create_task() cannot safely be called there.
        #
        # This fixes:
        #
        # RuntimeWarning:
        # coroutine ... safe_progress was never awaited
        # ====================================================

        loop = asyncio.get_running_loop()

        async def safe_progress(
            percent,
            done,
            total_bytes,
            speed,
            eta,
        ):

            if video.event.is_set():
                return

            now = time.monotonic()

            if (
                now - last_update[0] < 1.0
                and percent < 100
            ):
                return

            last_update[0] = now

            if total > 1:

                text = (
                    "🎵 Downloading\n\n"
                    f"{idx:02d} - {title}"
                )

            else:

                text = (
                    "🎵 Downloading\n\n"
                    f"{title}"
                )

            text += (
                "\n\n"
                f"{progress_bar(percent)} "
                f"{percent:5.1f}%\n"
                f"Size: {human_bytes(done)}"
            )

            if total_bytes:

                text += (
                    f" / "
                    f"{human_bytes(total_bytes)}"
                )

            if speed:

                text += (
                    f"\nSpeed: "
                    f"{human_bytes(speed)}/s"
                )

            if eta is not None:

                text += (
                    f"\nETA: "
                    f"{human_time(eta)}"
                )

            if total > 1:

                text += (
                    "\n\nPlaylist: "
                    f"{job.playlist_done}/"
                    f"{job.playlist_total}"
                )

            await self._edit_video(
                application.bot,
                job,
                video,
                text,
                True,
            )

        # ====================================================
        # THREAD-SAFE PROGRESS CALLBACK
        # ====================================================

        def progress_cb(
            percent,
            done,
            total_bytes,
            speed,
            eta,
        ):

            if loop.is_closed():
                return

            try:

                asyncio.run_coroutine_threadsafe(
                    safe_progress(
                        percent,
                        done,
                        total_bytes,
                        speed,
                        eta,
                    ),
                    loop,
                )

            except RuntimeError:
                pass

        # ====================================================
        # DOWNLOAD
        # ====================================================

        try:

            path, info = await asyncio.wait_for(
                self.youtube.download_video(
                    url,
                    job.user_id,
                    video_dir,
                    idx if total > 1 else 0,
                    title,
                    progress_cb,
                    video.event,
                ),
                timeout=JOB_TIMEOUT,
            )

            # ------------------------------------------------
            # CANCELLED AFTER DOWNLOAD
            # ------------------------------------------------

            if video.event.is_set():

                raise DownloadCancelled()

            # =================================================
            # UPLOAD
            # =================================================

            video.status = "uploading"

            job.status = (
                f"uploading {idx}/{total}"
                if total > 1
                else "uploading"
            )

            async def upload_progress(
                percent,
                done,
                total_bytes,
            ):

                if video.event.is_set():
                    return

                text = (
                    "📤 Uploading\n\n"
                    f"{path.name}\n\n"
                    f"{progress_bar(percent)} "
                    f"{percent:5.1f}%\n"
                    f"{human_bytes(done)}"
                )

                if total_bytes:

                    text += (
                        f" / "
                        f"{human_bytes(total_bytes)}"
                    )

                await self._edit_video(
                    application.bot,
                    job,
                    video,
                    text,
                    True,
                )

            def upload_cb(
                percent,
                done,
                total_bytes,
            ):

                if loop.is_closed():
                    return

                try:

                    asyncio.run_coroutine_threadsafe(
                        upload_progress(
                            percent,
                            done,
                            total_bytes,
                        ),
                        loop,
                    )

                except RuntimeError:
                    pass

            uploader = (
                application
                .bot_data[
                    "uploader"
                ]
            )

            await uploader.upload_user_and_dump(
                job.chat_id,
                path,
                path.name,
                upload_cb,
                video.event,
            )

            # ------------------------------------------------
            # Check cancellation
            # ------------------------------------------------

            if video.event.is_set():

                raise DownloadCancelled()

            # ------------------------------------------------
            # Remove local file
            # ------------------------------------------------

            path.unlink(
                missing_ok=True
            )

            video.status = "completed"

            # =================================================
            # COMPLETED
            # =================================================

            if total > 1:

                completed_text = (
                    "✅ Completed\n\n"
                    f"{path.name}\n\n"
                    f"Playlist: "
                    f"{job.playlist_done + 1}/"
                    f"{job.playlist_total}"
                )

            else:

                completed_text = (
                    "✅ Completed\n\n"
                    f"{path.name}"
                )

            await self._edit_video(
                application.bot,
                job,
                video,
                completed_text,
                False,
            )

        except DownloadCancelled:

            video.status = "cancelled"

            await self._edit_video(
                application.bot,
                job,
                video,
                (
                    "❌ Cancelled\n\n"
                    f"{idx:02d} - {title}\n\n"
                    "➡️ Continuing with the playlist..."
                    if total > 1
                    else
                    (
                        "❌ Cancelled\n\n"
                        f"{title}"
                    )
                ),
                False,
            )

            raise

        except asyncio.CancelledError:

            video.status = "cancelled"

            raise

        except Exception as exc:

            video.status = "failed"

            await self._edit_video(
                application.bot,
                job,
                video,
                (
                    "⚠️ Download failed\n\n"
                    f"{idx:02d} - {title}\n\n"
                    f"{type(exc).__name__}: "
                    f"{str(exc)[:500]}"
                    if total > 1
                    else
                    (
                        "⚠️ Download failed\n\n"
                        f"{title}\n\n"
                        f"{type(exc).__name__}: "
                        f"{str(exc)[:500]}"
                    )
                ),
                False,
            )

            raise

        finally:

            # ------------------------------------------------
            # Remove ONLY this video's cancellation state.
            # Other concurrent videos remain untouched.
            # ------------------------------------------------

            job.active_videos.pop(
                video.token,
                None,
            )

    # ========================================================
    # CANCEL
    # ========================================================

    async def cancel(
        self,
        cancel_key,
        user_id,
    ):

        if not cancel_key:
            return False

        # ====================================================
        # FORMAT:
        #
        # cancel:<JOB_ID>:<VIDEO_TOKEN>
        #
        # The callback handler removes "cancel:" and passes:
        #
        # JOB_ID:VIDEO_TOKEN
        # ====================================================

        parts = cancel_key.split(
            ":",
            1,
        )

        job_id = parts[0]

        video_token = (
            parts[1]
            if len(parts) > 1
            else None
        )

        job = self.jobs.get(
            job_id
        )

        if not job:
            return False

        if job.user_id != user_id:
            return False

        # ====================================================
        # OLD/MAIN JOB CANCEL
        #
        # Kept as fallback.
        # ====================================================

        if not video_token:

            if len(
                job.active_videos
            ) == 1:

                video = next(
                    iter(
                        job.active_videos.values()
                    )
                )

                video.event.set()

                return True

            return False

        # ====================================================
        # INDIVIDUAL VIDEO CANCEL
        # ====================================================

        video = job.active_videos.get(
            video_token
        )

        if not video:
            return False

        if video.status not in (
            "downloading",
            "uploading",
        ):
            return False

        video.event.set()

        return True

    # ========================================================
    # STATUS
    # ========================================================

    def status_text(
        self,
        user_id,
    ):

        active = [
            job
            for job in self.jobs.values()
            if job.user_id == user_id
        ]

        if not active:

            return "📊 No active jobs."

        lines = [
            "📊 Active jobs\n"
        ]

        for job in active:

            lines.append(
                f"• `{job.id}` — "
                f"{job.status}"
            )

            for video in (
                job.active_videos.values()
            ):

                lines.append(
                    f"  ↳ {video.index:02d} "
                    f"{video.status}: "
                    f"{video.title}"
                )

        lines.append(
            "\nMaximum concurrent downloads: "
            f"{MAX_CONCURRENT}"
        )

        return "\n".join(lines)

    # ========================================================
    # SHUTDOWN
    # ========================================================

    async def shutdown(self):

        for job in list(
            self.jobs.values()
        ):

            # Cancel every currently active
            # video independently.

            for video in list(
                job.active_videos.values()
            ):

                video.event.set()

            if job.task:

                job.task.cancel()
