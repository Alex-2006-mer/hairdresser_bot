from telebot import types
from bot_in import bot
from database import ensure_client
from handlers.default_handlers.booking import markup

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    ensure_client(m.from_user)
    bot.reply_to(m,
        "👋 Привет! Добро пожаловать.\n"
        "Используй кнопки внизу 👇",
        reply_markup=markup(m)  # ✅ передаём кнопки
    )