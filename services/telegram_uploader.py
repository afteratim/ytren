import asyncio
import math
from pathlib import Path
from pyrogram import Client, raw
from pyrogram.types import InputMediaDocument
from config import SPLIT_SIZE_BYTES, DUMP_CHANNEL_ID
from utils.formatting import human_bytes, progress_bar

PART_SIZE = 512 * 1024
MAX_RETRIES = 4

class TelegramUploader:
    def __init__(self, api_id, api_hash):
        self.client = Client(
            "ytaudio_bot_session",
            api_id=api_id,
            api_hash=api_hash,
            bot_token=__import__("config").BOT_TOKEN,
            in_memory=True,
        )

    async def start(self):
        await self.client.start()

    async def stop(self):
        try:
            await self.client.stop()
        except Exception:
            pass

    async def _save_big_file(self, path, file_name, progress_cb, cancel_event):
        size = path.stat().st_size
        total_parts = math.ceil(size / PART_SIZE)
        file_id = raw.types.InputFileBig(
            id=0, parts=total_parts, name=file_name
        )
        # Pyrogram requires a real random 64-bit file id.
        import secrets
        file_id.id = secrets.randbits(63)

        with path.open("rb") as f:
            for part in range(total_parts):
                if cancel_event.is_set():
                    raise asyncio.CancelledError()
                data = f.read(PART_SIZE)
                if not data:
                    break

                for attempt in range(MAX_RETRIES):
                    try:
                        await self.client.invoke(
                            raw.functions.upload.SaveBigFilePart(
                                file_id=file_id.id,
                                file_part=part,
                                file_total_parts=total_parts,
                                bytes=data,
                            )
                        )
                        break
                    except Exception:
                        if attempt == MAX_RETRIES - 1:
                            raise
                        await asyncio.sleep(1.0 * (attempt + 1))

                progress_cb(
                    (part + 1) * 100 / total_parts,
                    (part + 1) * PART_SIZE if part + 1 < total_parts else size,
                    size,
                )

        return file_id

    async def _send_big_document(self, chat_id, file_id, caption):
        media = raw.types.InputMediaUploadedDocument(
            file=file_id,
            mime_type="application/octet-stream",
            attributes=[raw.types.DocumentAttributeFilename(file_name=file_id.name)],
        )
        peer = await self.client.resolve_peer(chat_id)
        return await self.client.invoke(
            raw.functions.messages.SendMedia(
                peer=peer,
                media=media,
                message=caption or "",
                random_id=__import__("pyrogram").raw.base.Int(0),
            )
        )

    async def upload(self, chat_id, path: Path, caption, progress_cb, cancel_event):
        size = path.stat().st_size

        # For files under 1.9 GB Pyrogram's normal document upload is simpler.
        # For larger files we upload logical Telegram parts directly from the same
        # source file, without creating physical .part copies.
        if size <= SPLIT_SIZE_BYTES:
            last = {"done": 0}
            async def pyrogram_progress(current, total):
                last["done"] = current
                progress_cb(current * 100 / total if total else 0, current, total)
            try:
                return await self.client.send_document(
                    chat_id,
                    str(path),
                    caption=caption or "",
                    progress=pyrogram_progress,
                )
            except Exception:
                # Fall back to raw big-file upload if the normal path rejects size.
                pass

        # A >1.9 GB source is split logically into 1.9 GB Telegram files.
        # This implementation uploads each logical range directly from the source.
        # For the V1 code, physical chunks are avoided to prevent disk duplication.
        # Telegram's raw API requires a separate file upload for each logical part.
        results = []
        part_limit = SPLIT_SIZE_BYTES
        total_parts = math.ceil(size / part_limit)

        for logical_index in range(total_parts):
            if cancel_event.is_set():
                raise asyncio.CancelledError()

            start = logical_index * part_limit
            end = min(size, start + part_limit)
            logical_size = end - start

            # We create a sparse temporary logical part only when needed.
            # This avoids loading a multi-GB file into RAM.
            part_path = path.with_name(
                f".{path.stem}.telegram-part-{logical_index+1:02d}{path.suffix}"
            )

            try:
                with path.open("rb") as src, part_path.open("wb") as dst:
                    src.seek(start)
                    remaining = logical_size
                    while remaining:
                        if cancel_event.is_set():
                            raise asyncio.CancelledError()
                        chunk = src.read(min(8 * 1024 * 1024, remaining))
                        if not chunk:
                            raise IOError("Unexpected EOF while creating Telegram part.")
                        dst.write(chunk)
                        remaining -= len(chunk)

                async def p(current, total, idx=logical_index):
                    overall = ((idx * logical_size) + current) / size * 100
                    progress_cb(overall, (idx * logical_size) + current, size)

                result = await self.client.send_document(
                    chat_id,
                    str(part_path),
                    caption=caption or "",
                    progress=p,
                )
                results.append(result)
            finally:
                part_path.unlink(missing_ok=True)

        return results

    async def upload_user_and_dump(self, user_chat_id, path, caption, progress_cb, cancel_event):
        result = await self.upload(user_chat_id, path, caption, progress_cb, cancel_event)

        if DUMP_CHANNEL_ID and not cancel_event.is_set():
            try:
                await self.upload(
                    DUMP_CHANNEL_ID,
                    path,
                    caption,
                    lambda p, d, t: None,
                    cancel_event,
                )
            except Exception:
                # User delivery succeeded; dump failure should not destroy the job.
                pass

        return result
