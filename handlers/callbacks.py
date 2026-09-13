from telegram import Update
from telegram.ext import ContextTypes
from utils.auth import is_allowed

async def callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_allowed(update.effective_user.id):
        return

    data = query.data or ""
    if not data.startswith("cancel:"):
        return

    job_id = data.split(":", 1)[1]
    manager = context.application.bot_data["manager"]
    result = await manager.cancel(job_id, update.effective_user.id)

    if result:
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
