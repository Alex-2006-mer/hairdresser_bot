
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

@bot.callback_query_handler(func=lambda c: c.data == "cancel_flow")
def cb_cancel_flow(c: types.CallbackQuery):
    user_states.pop(c.message.chat.id, None)
    try:
        bot.edit_message_text("Запись отменена.", c.message.chat.id, c.message.message_id)
    except Exception:
        pass
    bot.answer_callback_query(c.id)

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

    bot.answer_callback_query(c.id, f"Вы забронировали {slot} {day.strftime('%d.%m.%Y')}.")
    try:
        bot.delete_message(c.message.chat.id, c.message.message_id)
    except Exception:
        try:
            bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        except Exception:
            pass

    bot.send_message(user.id, f"✅ Ваша запись: {day.strftime('%d.%m.%Y')} в {slot}. (ID {booking_id})")

    # notify admins
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, f"📝 Новая запись: {user.first_name} {user.last_name or ''} (@{user.username or '—'})\n"
                                       f"Дата: {day.strftime('%d.%m.%Y')}\nВремя: {slot}\nID: {booking_id}")
        except Exception:
            pass

    user_states.pop(c.message.chat.id, None)


def show_main_menu(chat_id: int, user_id: int):
    kb = types.InlineKeyboardMarkup(row_width=2)

    # кнопки для всех
    kb.add(types.InlineKeyboardButton("📅 Записаться", callback_data="menu_book"))
    kb.add(types.InlineKeyboardButton("📖 Мои записи", callback_data="menu_mybookings"))
    kb.add(types.InlineKeyboardButton("❌ Отменить запись", callback_data="menu_cancel"))

    # кнопки только для админа
    if user_id in ADMINS:
        kb.add(types.InlineKeyboardButton("📴 День выходной", callback_data="menu_dayoff"))
        kb.add(types.InlineKeyboardButton("✅ Открыть день", callback_data="menu_openday"))
        kb.add(types.InlineKeyboardButton("🗓 Выходной по неделе", callback_data="menu_weekdayoff"))
        kb.add(types.InlineKeyboardButton("📢 Объявление", callback_data="menu_announce"))
        kb.add(types.InlineKeyboardButton("🗑 Удалить запись", callback_data="menu_delbooking"))
        kb.add(types.InlineKeyboardButton("📊 Статистика", callback_data="menu_stats"))
        kb.add(types.InlineKeyboardButton("➕ Добавить клиента", callback_data="menu_addclient"))

    bot.send_message(chat_id, "📋 Главное меню:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("menu_"))
def cb_menu(c: types.CallbackQuery):
    action = c.data.split("_", 1)[1]

    # общие действия
    if action == "book":
        cmd_book(c.message)
    elif action == "mybookings":
        cmd_mybookings(c.message)
    elif action == "cancel":
        cmd_cancel(c.message)

    # админские действия
    elif c.from_user.id in ADMINS:
        if action == "dayoff":
            bot.send_message(c.from_user.id, "Введите: /dayoff YYYY-MM-DD")
        elif action == "openday":
            bot.send_message(c.from_user.id, "Введите: /openday YYYY-MM-DD")
        elif action == "weekdayoff":
            bot.send_message(c.from_user.id, "Введите: /weekdayoff N (0=Mon ... 6=Sun)")
        elif action == "announce":
            bot.send_message(c.from_user.id, "Введите: /announce текст")
        elif action == "delbooking":
            bot.send_message(c.from_user.id, "Введите: /delbooking ID")
        elif action == "stats":
            bot.send_message(c.from_user.id, "Введите: /stats YYYY-MM или /stats N(дней)")
        elif action == "addclient":
            # start admin manual booking flow
            start_admin_booking_flow(c)
    else:
        bot.answer_callback_query(c.id, "⛔ Нет доступа.")

    bot.answer_callback_query(c.id)


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
    bot.send_message(m.chat.id, "Выберите запись, которую хотите отменить:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("cancel_booking:"))
def cb_cancel_booking(c: types.CallbackQuery):
    try:
        booking_id = int(c.data.split(":", 1)[1])
    except Exception:
        bot.answer_callback_query(c.id, "Ошибка.")
        return
    # get booking and ensure owner
    cur.execute("SELECT client_id, booking_date, booking_time FROM bookings WHERE id=? AND status='booked'", (booking_id,))
    r = cur.fetchone()
    if not r:
        bot.answer_callback_query(c.id, "Запись не найдена или уже отменена.")
        return
    # find user who pressed button
    uid = c.from_user.id
    if uid != r["client_id"] and uid not in ADMINS:
        bot.answer_callback_query(c.id, "Вы не можете отменять эту запись.")
        return
    # cancel
    cur.execute("UPDATE bookings SET status='canceled' WHERE id=?", (booking_id,))
    conn.commit()
    bot.answer_callback_query(c.id, "Запись отменена.")
    try:
        bot.edit_message_text("Запись отменена.", c.message.chat.id, c.message.message_id)
    except Exception:
        pass

    # notify admins
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, f"❌ Запись отменена (id {booking_id}) — инициатор: @{c.from_user.username or c.from_user.id}")
        except Exception:
            pass


