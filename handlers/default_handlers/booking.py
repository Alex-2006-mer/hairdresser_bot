
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton,InlineKeyboardMarkup
from telebot.apihelper import answer_callback_query
from telebot import types
from bot_in import bot
from database import cur,available_slots,fmt_booking_row,conn,ensure_client,user_states,date_keyboard,is_weekday_off,is_manual_day_off,time_keyboard
from config.config import BOOKING_CUTOFF_HOURS, ADMINS
from datetime import datetime,timedelta
from handlers.default_handlers.admin import start_admin_booking_flow


@bot.message_handler(commands=["book"])
def cmd_book(m: types.Message):
    ensure_client(m.from_user)
    user_states[m.chat.id] = {"step": "select_date"}
    bot.send_message(m.chat.id, "Выберите дату для записи:", reply_markup=date_keyboard())
    # send_clean_message(bot,m.chat.id,"Выберите дату для записи:",reply_markup=date_keyboard())
# --------------------------------------------------------------------------------------------------
@bot.message_handler(func=lambda message: message.text == "Записатся")
def cmd_book(m: types.Message):
    ensure_client(m.from_user)
    user_states[m.chat.id] = {"step": "select_date"}
    bot.send_message(m.chat.id, "Выберите дату для записи:", reply_markup=date_keyboard())

@bot.message_handler(func=lambda message: message.text == "Меню")
def cmd_menu(m: types.Message):
    ensure_client(m.from_user)
    bot.send_message(m.chat.id, "Ваше меню", reply_markup=menu_user(m))

@bot.message_handler(func=lambda m: m.text == "Записать клиента")
def start_admin_booking_flow(m: types.Message):
    chat_id = m.chat.id

    if chat_id not in ADMINS:
        bot.send_message(chat_id, "⛔ Нет доступа.")
        return

    user_states[chat_id] = {
        "role": "admin",
        "step": "admin_select_date"
    }

    bot.send_message(
        chat_id,
        "📅 Выберите дату:",
        reply_markup=date_keyboard(prefix="admin_date:")
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_date:"))
def cb_admin_select_date(c: types.CallbackQuery):
    chat_id = c.message.chat.id
    selected = c.data.split(":",1)[1]
    day = datetime.fromisoformat(selected).date()

    state = user_states.get(chat_id)
    if not state or state.get("role") != "admin":
        bot.answer_callback_query(c.id, "Ошибка состояния")
        return

    state["date"] = selected
    state["step"] = "admin_select_time"
    if is_weekday_off(day):
        bot.edit_message_text("❌ Салон не работает в этот день недели. Выберите другой день.",
                              c.message.chat.id, c.message.message_id)
        return

    if is_manual_day_off(day):
        bot.edit_message_text("❌ В этот день салон отмечен как выходной. Выберите другой день.",
                              c.message.chat.id, c.message.message_id)
        return

    slots = available_slots(day)
    if not slots:
        bot.edit_message_text("На выбранный день нет свободных слотов. Попробуйте другой день.",
                              c.message.chat.id, c.message.message_id)
        return
    day = datetime.fromisoformat(selected).date()
    slots = available_slots(day)

    bot.edit_message_text(
        f"Выберите время {day.strftime('%d.%m.%Y')}",
        chat_id,
        c.message.message_id,
        reply_markup=time_keyboard(slots, prefix="admin_time:")
    )

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_time:"))
def cb_admin_select_time(c: types.CallbackQuery):
    chat_id = c.message.chat.id
    slot = c.data.split(":",1)[1]

    state = user_states.get(chat_id)
    if not state or state.get("role") != "admin":
        bot.answer_callback_query(c.id, "Ошибка состояния")
        return

    state["time"] = slot
    state["step"] = "admin_enter_name"

    bot.edit_message_text(
        "Введите имя клиента:",
        chat_id,
        c.message.message_id
    )
    bot.answer_callback_query(c.id)

@bot.message_handler(func=lambda m:
    user_states.get(m.chat.id, {}).get("step") == "admin_enter_name")
def admin_enter_name(m: types.Message):
    chat_id = m.chat.id
    state = user_states.get(chat_id)

    if not state or state.get("role") != "admin":
        bot.send_message(chat_id, "Начните заново")
        return

    name = m.text.strip()
    if not name:
        bot.send_message(chat_id, "Имя пустое, введите ещё раз:")
        return

    booking_date = state.get("date")
    booking_time = state.get("time")

    if not booking_date or not booking_time:
        bot.send_message(chat_id, "Ошибка данных")
        return

    cur.execute("SELECT MIN(user_id) FROM clients WHERE user_id < 0")
    row = cur.fetchone()
    fake_user_id = (row[0] - 1) if row and row[0] else -1

    cur.execute(
        "INSERT INTO clients(user_id, username, full_name, registered_at) VALUES(?, ?, ?, ?)",
        (fake_user_id, "", name, datetime.now().isoformat())
    )

    cur.execute("""
        INSERT INTO bookings(client_id, booking_date, booking_time, status, created_at, reminder_sent)
        VALUES(?, ?, ?, 'booked', ?, 0)
    """, (fake_user_id, booking_date, booking_time, datetime.now().isoformat()))

    conn.commit()
    booking_id = cur.lastrowid

    bot.send_message(
        chat_id,
        f"📝 Новая запись: {name}\nДата: {booking_date}\nВремя {booking_time}\nID: {booking_id}"
    )

    user_states.pop(chat_id, None)

# -----------------------------------------------------------------------
@bot.callback_query_handler(func=lambda c: c.data.startswith("select_date:"))
def cb_select_date(c: types.CallbackQuery):
    selected = c.data.split(":", 1)[1]
    day = datetime.fromisoformat(selected).date()

    if is_weekday_off(day):
        bot.edit_message_text("❌ Салон не работает в этот день недели. Выберите другой день.",
                              c.message.chat.id, c.message.message_id)
        return

    if is_manual_day_off(day):
        bot.edit_message_text("❌ В этот день салон отмечен как выходной. Выберите другой день.",
                              c.message.chat.id, c.message.message_id)
        return

    slots = available_slots(day)
    if not slots:
        bot.edit_message_text("На выбранный день нет свободных слотов. Попробуйте другой день.",
                              c.message.chat.id, c.message.message_id)
        return

    user_states[c.message.chat.id] = {"step": "select_time", "date": selected}
    bot.edit_message_text(f"Вы выбрали {day.strftime('%d.%m.%Y')}. Выберите время:", c.message.chat.id,
                          c.message.message_id, reply_markup=time_keyboard(slots))

@bot.callback_query_handler(func=lambda c: c.data.startswith("book:"))
def cb_book(c: types.CallbackQuery):
    # existing user booking flow
    slot = c.data.split(":", 1)[1]
    user = c.from_user
    state = user_states.get(c.message.chat.id)
    if not state or state.get("step") != "select_time":
        bot.answer_callback_query(c.id, "Ошибка — начните /book заново.")
        return

    booking_date = state["date"]
    day = datetime.fromisoformat(booking_date).date()

    # double check week/day off
    if is_weekday_off(day) or is_manual_day_off(day):
        bot.answer_callback_query(c.id, "На эту дату запись невозможна.")
        return

    # check slot still free
    cur.execute("SELECT 1 FROM bookings WHERE booking_date=? AND booking_time=? AND status='booked'", (booking_date, slot))
    if cur.fetchone():
        bot.answer_callback_query(c.id, "Этот слот уже заняли.")
        return

    # check cutoff: cannot book closer than BOOKING_CUTOFF_HOURS
    slot_dt = datetime.combine(day, datetime.min.time()).replace(hour=int(slot.split(":")[0]), minute=int(slot.split(":")[1]))
    if slot_dt < datetime.now() + timedelta(hours=BOOKING_CUTOFF_HOURS):
        bot.answer_callback_query(c.id, f"Нельзя записаться ближе чем за {BOOKING_CUTOFF_HOURS} час(ов).")
        return

    # save
    ensure_client(user)
    cur.execute("INSERT INTO bookings(client_id, booking_date, booking_time, status, created_at, reminder_sent) VALUES(?, ?, ?, 'booked', ?, 0)",
                (user.id, booking_date, slot, datetime.now().isoformat()))
    conn.commit()
    booking_id = cur.lastrowid
    bot.edit_message_text(
        f"✅ Запись подтверждена!\n\n"
        f"⏰ Ваша запись: {day.strftime('%d.%m.%Y')} в {slot}",
        c.message.chat.id,
        c.message.message_id)

    # notify admins
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, f"📝 Новая запись: {user.first_name} {user.last_name or ''} (@{user.username or '—'})\n"
                                       f"Дата: {day.strftime('%d.%m.%Y')}\nВремя: {slot}\nID: {booking_id}")
        except Exception:
            pass

    user_states.pop(c.message.chat.id, None)

def menu_user(message):
    user_id = message.from_user.id

    if not user_id in ADMINS:
        btn_1 = InlineKeyboardButton(text="📖 Мои записи", callback_data="mybookings")
        btn_2 = InlineKeyboardButton(text="❌ Отменить запись", callback_data="cancel")

        keyboard_2 = InlineKeyboardMarkup()
        keyboard_2.add(btn_1,btn_2)
        return keyboard_2
    else:
        k_1 = InlineKeyboardButton(text="📅 День выходной", callback_data="dayoff")
        k_2 = InlineKeyboardButton(text="✅ Открыть день", callback_data="openday")
        k_3 = InlineKeyboardButton(text="🗑 Удалить запись", callback_data="delbooking")
        k_4 = InlineKeyboardButton(text="Клиенты", callback_data="clients")

        keyboard_3 = InlineKeyboardMarkup()
        keyboard_3.add(k_1, k_2, k_3, k_4)
        return keyboard_3

def markup(message):
    user_id = message.from_user.id
    if not user_id in ADMINS:
        button_1 = KeyboardButton(text="Записатся")
        button_2 = KeyboardButton(text="Меню")

        keyword = ReplyKeyboardMarkup(resize_keyboard=True)
        keyword.add(button_1, button_2)
        return keyword
    else:
        button_1 = KeyboardButton(text="Записать клиента")
        button_2 = KeyboardButton(text="Меню")

        keyword = ReplyKeyboardMarkup(resize_keyboard=True)
        keyword.add(button_1, button_2)
        return keyword


@bot.message_handler(commands=["mybookings"])
def cmd_mybookings(m: types.Message):
    cur.execute("""
        SELECT b.id, b.booking_date, b.booking_time, c.full_name, c.username
        FROM bookings b JOIN clients c ON b.client_id=c.user_id
        WHERE b.client_id=? AND b.status='booked'
        ORDER BY b.booking_date, b.booking_time
    """, (m.from_user.id,))
    rows = cur.fetchall()
    if not rows:
        bot.reply_to(m, "У вас нет активных записей.")
        return
    text = "Ваши записи:\n" + "\n".join([fmt_booking_row(r) for r in rows])
    bot.reply_to(m, text)
#
@bot.message_handler(commands=["cancel"])
def cmd_cancel(m: types.Message):
    # show user's active bookings with inline buttons to cancel
    cur.execute("SELECT id, booking_date, booking_time FROM bookings WHERE client_id=? AND status='booked' ORDER BY booking_date, booking_time", (m.from_user.id,))
    rows = cur.fetchall()
    if not rows:
        bot.reply_to(m, "У вас нет активных записей.")
        return
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        kb.add(types.InlineKeyboardButton(text=f"{r['booking_date']} {r['booking_time']}", callback_data=f"cancel_booking:{r['id']}"))
    bot.edit_message_text(
        "Выберите запись, которую хотите отменить:",
        m.message.chat.id,
        m.message.message_id,
        reply_markup=kb
    )

    bot.answer_callback_query(m.id)

@bot.callback_query_handler(func=lambda c: c.data == "cancel")
def cb_cancel_menu(c: types.CallbackQuery):
    cur.execute(
        "SELECT id, booking_date, booking_time FROM bookings "
        "WHERE client_id=? AND status='booked' "
        "ORDER BY booking_date, booking_time",
        (c.from_user.id,))
    rows = cur.fetchall()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "У вас нет активных записей.")
        return
    kb = types.InlineKeyboardMarkup()
    for r in rows:
        kb.add(types.InlineKeyboardButton(text=f"{r['booking_date']} {r['booking_time']}",callback_data=f"cancel_booking:{r['id']}"))
    bot.send_message(c.message.chat.id, "Выберите запись, которую хотите отменить:",reply_markup=kb)
    bot.answer_callback_query(c.id)

@bot.callback_query_handler(func=lambda c: c.data == "mybookings")
def cmd_mybookings(c: types.CallbackQuery):
    cur.execute("""
        SELECT b.id, b.booking_date, b.booking_time, c.full_name, c.username
        FROM bookings b JOIN clients c ON b.client_id=c.user_id
        WHERE b.client_id=? AND b.status='booked'
        ORDER BY b.booking_date, b.booking_time
    """,
        (c.from_user.id,))
    rows = cur.fetchall()
    if not rows:
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "У вас нет активных записей.")
        return
    text = "Ваши записи:\n" + "\n".join([fmt_booking_row(r) for r in rows])
    bot.send_message(c.message.chat.id, text)


