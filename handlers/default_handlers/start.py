from telebot import types
from bot_in import bot
from database import ensure_client
from handlers.default_handlers.booking import cmd_book, show_main_menu


def user_reply_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row(
        types.KeyboardButton("📅 Записаться"),
        types.KeyboardButton("📋 Меню"),
    )
    return kb

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    ensure_client(m.from_user)
    # show active announcements briefly (we'll reuse announcements as a simple broadcast mechanism via /announce)
    bot.reply_to(m, "👋 Привет! Добро пожаловать.\n"
                    "Доступные команды:\n"
                    "/book — забронировать время\n"
                    "/mybookings — мои записи\n"
                    "/cancel — отменить запись\n\n"
                    "Или используйте кнопки ниже 👇",
                    reply_markup=user_reply_keyboard())


@bot.message_handler(func=lambda m: m.text in {"📅 Записаться", "Записаться", "записаться", "записатся"})
def kb_book(m: types.Message):
    cmd_book(m)


@bot.message_handler(func=lambda m: m.text in {"📋 Меню", "Меню", "меню"})
def kb_menu(m: types.Message):
    show_main_menu(m.chat.id, m.from_user.id)
