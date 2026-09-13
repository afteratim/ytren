import re
import asyncio
from telegram import Update
from telegram.ext import ContextTypes
from utils.auth import is_allowed
from services.jobs import JobManager

YOUTUBE_RE = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/\S+",
    re.IGNORECASE
)

def extract_url(text: str):
    if not text:
        return None
    m = YOUTUBE_RE.search(text.strip())
    return m.group(0) if m else None

async def youtube_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    # Cookie documents are intentionally ignored here.
    if update.message.document:
        return

    url = extract_url(update.message.text)
    if not url:
        await update.message.reply_text("❌ Send a valid YouTube video or playlist URL.")
        return

    lower = url.lower()
    if any(x in lower for x in (
        "youtube.com/channel/",
        "youtube.com/@",
        "youtube.com/c/",
        "youtube.com/user/",
    )):
        await update.message.reply_text(
            "❌ YouTube channel URLs are not supported. Send a video or playlist URL."
        )
        return

    manager: JobManager = context.application.bot_data["manager"]
    await manager.submit(
        user_id=update.effective_user.id,
        chat_id=update.effective_chat.id,
        url=url,
        application=context.application,
    )
