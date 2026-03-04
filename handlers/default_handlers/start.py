from telebot import types
from bot_in import bot
from handlers.default_handlers.booking import ensure_client, markup
# from config.config import ADMINS

# @bot.message_handler(commands=["start"])
# def cmd_start(m: types.Message):
#     ensure_client(m.from_user)
#     # show active announcements briefly (we'll reuse announcements as a simple broadcast mechanism via /announce)
#     bot.reply_to(m, "👋 Привет! Добро пожаловать.\n"
#                     "Доступные команды:\n"
#                     "/book — забронировать время\n"
#                     "/mybookings — мои записи\n"
#                     "/cancel — отменить запись\n",
#                  reply_markup=markup(m))


@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    ensure_client(m.from_user)
    bot.send_message(m.chat.id, '''Привет!
Я — твой помощник для записи на стрижку 💈\n
С моей помощью ты можешь:
- 📅 Быстро выбрать дату и время
- ✂️ Ознакомиться с услугами и ценами
- 🔔 Получать напоминания о визите
- ❌ Отменять или переносить запись в пару кликов\n
Просто нажми кнопку ниже, чтобы записаться на стрижку и сэкономить время!''',
 reply_markup=markup(m))


# @bot.callback_query_handler(func=lambda c: c.data.startswith("select_date:"))
# def cb_select_date(c: types.CallbackQuery):
#     selected = c.data.split(":", 1)[1]
#     day = datetime.fromisoformat(selected).date()
#
#     if is_weekday_off(day):
#         bot.edit_message_text("❌ Салон не работает в этот день недели. Выберите другой день.",
#                               c.message.chat.id, c.message.message_id)
#         return
#
#     if is_manual_day_off(day):
#         bot.edit_message_text("❌ В этот день салон отмечен как выходной. Выберите другой день.",
#                               c.message.chat.id, c.message.message_id)
#         return
#
#     slots = available_slots(day)
#     if not slots:
#         bot.edit_message_text("На выбранный день нет свободных слотов. Попробуйте другой день.",
#                               c.message.chat.id, c.message.message_id)
#         return
#
#     user_states[c.message.chat.id] = {"step": "select_time", "date": selected}
#     bot.edit_message_text(f"Вы выбрали {day.strftime('%d.%m.%Y')}. Выберите время:", c.message.chat.id,
#                           c.message.message_id, reply_markup=time_keyboard(slots))