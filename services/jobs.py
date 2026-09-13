import asyncio
import uuid
import time
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import DOWNLOAD_DIR, MAX_CONCURRENT, JOB_TIMEOUT
from services.youtube import YoutubeService, DownloadCancelled
from utils.formatting import human_bytes, human_time, progress_bar

@dataclass
class VideoCancel:
    event: asyncio.Event = field(default_factory=asyncio.Event)

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
    current_cancel: VideoCancel | None = None
    started: float = field(default_factory=time.time)

class JobManager:
    def __init__(self):
        self.jobs = {}
        self.youtube = YoutubeService(DOWNLOAD_DIR)

    async def submit(self, user_id, chat_id, url, application):
        job_id = uuid.uuid4().hex[:10]
        job = Job(job_id, user_id, chat_id, url)
        self.jobs[job_id] = job
        msg = await application.bot.send_message(
            chat_id, f"🔎 Job `{job_id}` queued...\n\n{url}", parse_mode="Markdown"
        )
        job.message_id = msg.message_id
        job.task = asyncio.create_task(self._run(job, application))
        return job_id

    def _keyboard(self, job_id):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "❌ Cancel current video",
                callback_data=f"cancel:{job_id}"
            )]
        ])

    async def _edit(self, bot, job, text, markup=True):
        if not job.message_id:
            return
        try:
            await bot.edit_message_text(
                chat_id=job.chat_id,
                message_id=job.message_id,
                text=text,
                reply_markup=self._keyboard(job.id) if markup else None,
            )
        except Exception:
            pass

    async def _run(self, job, application):
        bot = application.bot
        workdir = DOWNLOAD_DIR / job.id
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            job.status = "analyzing"
            await self._edit(bot, job, "🔎 Reading YouTube information...")

            info = await asyncio.wait_for(
                self.youtube.get_info(job.url, job.user_id), timeout=120
            )

            if info.get("_type") == "playlist" or info.get("entries") is not None:
                entries = [e for e in (info.get("entries") or []) if e]
                if not entries:
                    raise RuntimeError("The playlist contains no downloadable videos.")

                job.playlist_total = len(entries)
                await self._edit(
                    bot, job,
                    f"📋 Playlist found\n\n"
                    f"Videos: {job.playlist_total}\n"
                    f"Workers: 2\n\n"
                    f"🎵 Downloading best available audio..."
                )
                await self._playlist(job, entries, application, workdir)
            else:
                job.playlist_total = 1
                await self._one_video(
                    job, job.url, 0, 1,
                    info.get("title") or "audio", application, workdir
                )

        except DownloadCancelled:
            job.status = "cancelled"
            await self._edit(bot, job, "❌ Current video cancelled.", False)
        except asyncio.CancelledError:
            job.status = "cancelled"
            await self._edit(bot, job, "❌ Job stopped.", False)
        except Exception as e:
            job.status = "error"
            await self._edit(
                bot, job,
                f"❌ Error\n\n{type(e).__name__}: {str(e)[:700]}",
                False
            )
        finally:
            job.current_cancel = None
            shutil.rmtree(workdir, ignore_errors=True)
            self.jobs.pop(job.id, None)

    async def _playlist(self, job, entries, application, workdir):
        queue = asyncio.Queue()
        for idx, entry in enumerate(entries, 1):
            await queue.put((idx, entry))

        async def worker():
            while True:
                try:
                    idx, entry = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                url = (
                    entry.get("webpage_url")
                    or entry.get("original_url")
                    or entry.get("url")
                )
                title = entry.get("title") or f"Audio {idx:02d}"

                try:
                    await self._one_video(
                        job, url, idx, len(entries), title, application, workdir
                    )
                except DownloadCancelled:
                    await self._edit(
                        application.bot, job,
                        f"❌ Cancelled: {idx:02d} - {title}\n\n"
                        f"➡️ Continuing with the next playlist video...",
                        True
                    )
                except Exception as e:
                    await self._edit(
                        application.bot, job,
                        f"⚠️ Failed: {idx:02d} - {title}\n\n"
                        f"{type(e).__name__}: {str(e)[:400]}\n\n"
                        f"➡️ Continuing...",
                        True
                    )
                finally:
                    job.playlist_done += 1
                    queue.task_done()

        workers = [
            asyncio.create_task(worker())
            for _ in range(min(MAX_CONCURRENT, len(entries)))
        ]
        await asyncio.gather(*workers)

        await self._edit(
            application.bot, job,
            f"✅ Playlist completed\n\n"
            f"Completed/processed: {job.playlist_done}/{job.playlist_total}",
            False
        )

    async def _one_video(self, job, url, idx, total, title, application, workdir):
        cancel = VideoCancel()
        job.current_cancel = cancel
        job.current_title = title
        job.current_index = idx

        video_dir = workdir / f"{idx:04d}" if idx else workdir / "single"
        video_dir.mkdir(parents=True, exist_ok=True)
        job.status = f"downloading {idx}/{total}" if total > 1 else "downloading"

        last_update = [0.0]

        async def safe_progress(percent, done, total_bytes, speed, eta):
            now = time.monotonic()
            if now - last_update[0] < 1.0 and percent < 100:
                return
            last_update[0] = now

            text = (
                f"🎵 Downloading\n\n"
                f"{idx:02d} - {title}" if total > 1 else
                f"🎵 Downloading\n\n{title}"
            )
            text += (
                f"\n\n{progress_bar(percent)} {percent:5.1f}%\n"
                f"Size: {human_bytes(done)}"
            )
            if total_bytes:
                text += f" / {human_bytes(total_bytes)}"
            if speed:
                text += f"\nSpeed: {human_bytes(speed)}/s"
            if eta is not None:
                text += f"\nETA: {human_time(eta)}"
            if total > 1:
                text += f"\n\nPlaylist: {job.playlist_done}/{job.playlist_total}"

            await self._edit(application.bot, job, text, True)

        def progress_cb(percent, done, total_bytes, speed, eta):
            asyncio.create_task(
                safe_progress(percent, done, total_bytes, speed, eta)
            )

        try:
            path, info = await asyncio.wait_for(
                self.youtube.download_video(
                    url, job.user_id, video_dir, idx if total > 1 else 0,
                    title, progress_cb, cancel.event
                ),
                timeout=JOB_TIMEOUT
            )

            if cancel.event.is_set():
                raise DownloadCancelled()

            job.status = f"uploading {idx}/{total}" if total > 1 else "uploading"

            async def upload_progress(percent, done, total_bytes):
                text = (
                    f"📤 Uploading\n\n"
                    f"{path.name}\n\n"
                    f"{progress_bar(percent)} {percent:5.1f}%\n"
                    f"{human_bytes(done)} / {human_bytes(total_bytes)}"
                )
                await self._edit(application.bot, job, text, True)

            def upload_cb(percent, done, total_bytes):
                asyncio.create_task(
                    upload_progress(percent, done, total_bytes)
                )

            uploader = application.bot_data["uploader"]
            await uploader.upload_user_and_dump(
                job.chat_id, path, path.name, upload_cb, cancel.event
            )

            path.unlink(missing_ok=True)

            await self._edit(
                application.bot, job,
                (
                    f"✅ Completed\n\n{path.name}\n\n"
                    f"Playlist: {job.playlist_done + 1}/{job.playlist_total}"
                    if total > 1 else
                    f"✅ Completed\n\n{path.name}"
                ),
                False
            )
        finally:
            # Clear only if this worker still owns the current cancel handle.
            if job.current_cancel is cancel:
                job.current_cancel = None

    async def cancel(self, job_id, user_id):
        job = self.jobs.get(job_id)
        if not job or job.user_id != user_id:
            return False

        # This cancels ONLY the video currently represented by the job's
        # progress message. It does not cancel the playlist or another worker.
        if job.current_cancel is not None:
            job.current_cancel.event.set()
            return True
        return False

    def status_text(self, user_id):
        active = [j for j in self.jobs.values() if j.user_id == user_id]
        if not active:
            return "📊 No active jobs."

        lines = ["📊 Active jobs\n"]
        for j in active:
            current = f" — {j.current_title}" if j.current_title else ""
            lines.append(f"• `{j.id}` — {j.status}{current}")
        lines.append(f"\nMaximum concurrent downloads: {MAX_CONCURRENT}")
        return "\n".join(lines)

    async def shutdown(self):
        for job in list(self.jobs.values()):
            if job.current_cancel:
                job.current_cancel.event.set()
            if job.task:
                job.task.cancel()
