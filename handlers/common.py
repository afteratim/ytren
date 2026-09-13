from telegram import Update
from telegram.ext import ContextTypes
from utils.auth import is_allowed
from services.jobs import JobManager

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("❌ You are not authorized to use this bot.")
        return
    await update.message.reply_text(
        "🎵 Send a YouTube video or playlist URL.\n\n"
        "The bot downloads the best available audio.\n\n"
        "Commands:\n"
        "/status - active jobs\n"
        "/cookie - reply to a cookie .txt document\n"
        "/removecookie - remove active cookies\n"
        "/help - help"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    await update.message.reply_text(
        "🎵 YouTube Audio Bot\n\n"
        "Send a YouTube video or playlist URL.\n"
        "Playlists are downloaded in full.\n"
        "Maximum 2 downloads run at once.\n"
        "Each active download has its own Cancel button.\n\n"
        "🍪 Cookies:\n"
        "1. Upload your cookies .txt file as a document.\n"
        "2. Reply to that document with /cookie.\n"
        "3. /removecookie disables it."
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    manager: JobManager = context.application.bot_data["manager"]
    await update.message.reply_text(manager.status_text(update.effective_user.id))
