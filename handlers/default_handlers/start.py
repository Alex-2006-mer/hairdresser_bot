from telebot import types
from bot_in import bot
from database import ensure_client

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    ensure_client(m.from_user)
    # show active announcements briefly (we'll reuse announcements as a simple broadcast mechanism via /announce)
    bot.reply_to(m, "👋 Привет! Добро пожаловать.\n"
                    "Доступные команды:\n"
                    "/book — забронировать время\n"
                    "/mybookings — мои записи\n"
                    "/cancel — отменить запись\n")