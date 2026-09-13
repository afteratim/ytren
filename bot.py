import asyncio
import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from config import BOT_TOKEN, API_ID, API_HASH
from services.jobs import JobManager
from services.telegram_uploader import TelegramUploader
from handlers.common import start, help_command, status
from handlers.cookies import cookie_command, removecookie_command
from handlers.youtube import youtube_message
from handlers.callbacks import callback_query

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("yt_dlp").setLevel(logging.WARNING)

manager = JobManager()
uploader = TelegramUploader(API_ID, API_HASH)

async def post_init(app: Application):
    await uploader.start()

async def post_shutdown(app: Application):
    await uploader.stop()
    await manager.shutdown()

async def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not configured.")
    if not API_ID or not API_HASH:
        raise RuntimeError("API_ID and API_HASH are required for MTProto uploads.")

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.bot_data["manager"] = manager
    app.bot_data["uploader"] = uploader

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("cookie", cookie_command))
    app.add_handler(CommandHandler("removecookie", removecookie_command))
    app.add_handler(CallbackQueryHandler(callback_query))
    app.add_handler(MessageHandler(filters.Document.ALL, youtube_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, youtube_message))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
