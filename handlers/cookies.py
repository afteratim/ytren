from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from config import COOKIE_DIR
from utils.auth import is_allowed

async def cookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.document:
        await msg.reply_text(
            "🍪 Reply to your uploaded cookie .txt file with /cookie."
        )
        return

    doc = msg.reply_to_message.document
    name = doc.file_name or "cookies.txt"

    if not name.lower().endswith(".txt"):
        await msg.reply_text("❌ Please reply to a .txt cookie file.")
        return

    user_dir = COOKIE_DIR / str(update.effective_user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    # One active cookie file per user.
    for old in user_dir.iterdir():
        if old.is_file():
            old.unlink(missing_ok=True)

    target = user_dir / "cookies.txt"
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(custom_path=str(target))

    await msg.reply_text(
        "🍪 Cookies loaded successfully.\n"
        "YouTube downloads will use them until /removecookie is used."
    )

async def removecookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    user_dir = COOKIE_DIR / str(update.effective_user.id)
    removed = False
    if user_dir.exists():
        for f in user_dir.iterdir():
            if f.is_file():
                f.unlink(missing_ok=True)
                removed = True

    await update.message.reply_text(
        "✅ Cookies removed." if removed else "ℹ️ No active cookie file was found."
    )
