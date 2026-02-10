from telebot import types
from bot_in import bot
from config.config import ADMINS
from datetime import datetime, timedelta
from database import cur,conn, user_states,time_keyboard, date_keyboard, is_weekday_off,is_manual_day_off,available_slots

@bot.message_handler(commands=["menu"])
def admin_menu(m: types.Message):
    if m.from_user.id not in ADMINS:
        bot.reply_to(m, "⛔ Нет доступа.")
        return

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton(text="📅 День выходной", callback_data="menu_dayoff"))
    kb.add(types.InlineKeyboardButton(text="✅ Открыть день", callback_data="menu_openday"))
    kb.add(types.InlineKeyboardButton(text="🗓 Выходной по неделе", callback_data="menu_weekdayoff"))
    kb.add(types.InlineKeyboardButton(text="📢 Объявление", callback_data="menu_announce"))
    kb.add(types.InlineKeyboardButton(text="🗑 Удалить запись", callback_data="menu_delbooking"))
    kb.add(types.InlineKeyboardButton(text="📊 Статистика", callback_data="menu_stats"))
    kb.add(types.InlineKeyboardButton(text="➕ Добавить клиента", callback_data="menu_addclient"))

    bot.send_message(m.chat.id, "Админ меню:", reply_markup=kb)


def admin_only(func):
    def wrapper(m: types.Message):
        if m.from_user.id not in ADMINS:
            bot.reply_to(m, "⛔ Нет доступа.")
        return func(m)
    return wrapper

@bot.message_handler(commands=["dayoff"])
@admin_only
def cmd_dayoff(m: types.Message):
    # /dayoff YYYY-MM-DD
    try:
        _, d = m.text.split(maxsplit=1)
        day = datetime.fromisoformat(d).date()
    except Exception:
        bot.reply_to(m, "Использование: /dayoff YYYY-MM-DD")
        return
    cur.execute("INSERT OR IGNORE INTO day_offs(date) VALUES(?)", (day.isoformat(),))
    conn.commit()
    bot.reply_to(m, f"✅ {day.strftime('%d.%m.%Y')} отмечен как выходной.")

@bot.message_handler(commands=["openday"])
@admin_only
def cmd_openday(m: types.Message):
    # /openday YYYY-MM-DD
    try:
        _, d = m.text.split(maxsplit=1)
        day = datetime.fromisoformat(d).date()
    except Exception:
        bot.reply_to(m, "Использование: /openday YYYY-MM-DD")
        return
    cur.execute("DELETE FROM day_offs WHERE date=?", (day.isoformat(),))
    conn.commit()
    bot.reply_to(m, f"✅ {day.strftime('%d.%m.%Y')} снова открыт для записи.")

@bot.message_handler(commands=["weekdayoff"])
@admin_only
def cmd_weekdayoff(m: types.Message):
    # /weekdayoff 0  (0=Monday .. 6=Sunday)  - toggle
    try:
        _, wd = m.text.split(maxsplit=1)
        wd = int(wd)
        if wd < 0 or wd > 6:
            raise ValueError
    except Exception:
        bot.reply_to(m, "Использование: /weekdayoff N  (0=Mon ... 6=Sun)")
        return
    cur.execute("SELECT 1 FROM weekday_offs WHERE weekday=?", (wd,))
    if cur.fetchone():
        cur.execute("DELETE FROM weekday_offs WHERE weekday=?", (wd,))
        conn.commit()
        bot.reply_to(m, f"✅ День недели {wd} теперь рабочий.")
    else:
        cur.execute("INSERT INTO weekday_offs(weekday) VALUES(?)", (wd,))
        conn.commit()
        bot.reply_to(m, f"✅ День недели {wd} теперь выходной.")

@bot.message_handler(commands=["announce"])
@admin_only
def cmd_announce(m: types.Message):
    # /announce текст...  -> простая рассылка всем клиентам
    text = m.text.partition(" ")[2].strip()
    if not text:
        bot.reply_to(m, "Использование: /announce текст объявления")
        return
    cur.execute("SELECT user_id FROM clients")
    clients = [r["user_id"] for r in cur.fetchall()]
    sent = 0
    for uid in clients:
        try:
            bot.send_message(uid, f"📢 Объявление:\n{text}")
            sent += 1
        except Exception:
            pass
    bot.reply_to(m, f"✅ Объявление отправлено {sent} клиентам.")

@bot.message_handler(commands=["clients"])
@admin_only
def cmd_clients(m: types.Message):
    cur.execute("SELECT user_id, username, full_name, registered_at FROM clients ORDER BY registered_at DESC")
    rows = cur.fetchall()
    if not rows:
        bot.reply_to(m, "Нет клиентов.")
        return
    text = "Клиенты:\n" + "\n".join([f"{r['full_name']} (@{r['username'] or '—'}) id:{r['user_id']}" for r in rows])
    # If too long, send as multiple messages
    for chunk_start in range(0, len(text), 4000):
        bot.send_message(m.chat.id, text[chunk_start:chunk_start+4000])

@bot.message_handler(commands=["delbooking"])
def cmd_delbooking(m: types.Message):
    if m.from_user.id not in ADMINS:
        bot.reply_to(m, "⛔ Нет доступа.")
        return
    try:
        # /delbooking ID
        _, booking_id = m.text.split(maxsplit=1)
        booking_id = int(booking_id)
    except Exception:
        bot.reply_to(m, "Использование: /delbooking <booking_id>")
        return

    # проверяем есть ли запись
    cur.execute("SELECT client_id, booking_date, booking_time FROM bookings WHERE id=?", (booking_id,))
    row = cur.fetchone()
    if not row:
        bot.reply_to(m, f"Запись с ID {booking_id} не найдена.")
        return

    # удаляем запись
    cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()

    bot.reply_to(m, f"✅ Запись {booking_id} удалена.")

    # уведомляем клиента
    try:
        bot.send_message(row["client_id"], f"❌ Ваша запись на {row['booking_date']} в {row['booking_time']} была удалена админом.")
    except Exception:
        pass

@admin_only
def cmd_broadcast_active(m: types.Message):
    # /broadcast_active N текст... => send to clients who had bookings in last N days
    parts = m.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(m, "Использование: /broadcast_active DAYS текст")
        return
    try:
        days = int(parts[1])
    except Exception:
        bot.reply_to(m, "Первый аргумент должен быть числом дней.")
        return
    text = parts[2]
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    cur.execute("SELECT DISTINCT c.user_id FROM clients c JOIN bookings b ON b.client_id=c.user_id WHERE b.created_at>=?", (cutoff,))
    rows = cur.fetchall()
    sent = 0
    for r in rows:
        try:
            bot.send_message(r["user_id"], f"📢 Для активных клиентов:\n{text}")
            sent += 1
        except Exception:
            pass
    bot.reply_to(m, f"Отправлено {sent} сообщений.")

@bot.message_handler(commands=["stats"])
@admin_only
def cmd_stats(m: types.Message):
    # /stats YYYY-MM  или /stats month_number  или просто /stats (последние 30 дней)
    parts = m.text.split(maxsplit=1)
    if len(parts) == 1:
        start = datetime.now() - timedelta(days=30)
        cur.execute("SELECT COUNT(*) as cnt FROM bookings WHERE created_at>=?", (start.isoformat(),))
        total = cur.fetchone()["cnt"]
        bot.reply_to(m, f"Статистика за последние 30 дней: всего бронирований: {total}")
        return
    arg = parts[1].strip()
    try:
        if "-" in arg:  # YYYY-MM
            year, mon = map(int, arg.split("-"))
            start = datetime(year, mon, 1)
            if mon == 12:
                end = datetime(year+1, 1, 1)
            else:
                end = datetime(year, mon+1, 1)
        else:
            days = int(arg)
            start = datetime.now() - timedelta(days=days)
            end = datetime.now()
        cur.execute("SELECT COUNT(*) as cnt FROM bookings WHERE created_at>=? AND created_at<?", (start.isoformat(), end.isoformat()))
        total = cur.fetchone()["cnt"]
        bot.reply_to(m, f"Статистика: бронирований {total} (с {start.date()} по {end.date()})")
    except Exception:
        bot.reply_to(m, "Ошибка в аргументе. Используйте /stats или /stats YYYY-MM или /stats N(дней)")

# ---------- Admin: manual booking flow (add offline client) ----------

def start_admin_booking_flow_for_user(admin_id: int):
    """Start admin add-client flow by admin user id (from message handlers)."""
    user_states[admin_id] = {"step": "admin_select_date"}
    bot.send_message(admin_id, "📅 Выберите дату для записи клиента:", reply_markup=date_keyboard(prefix="admin_select_date:"))


def start_admin_booking_flow(c: types.CallbackQuery):
    """Start the admin flow for manually adding a client booking (offline client)."""
    if c.from_user.id not in ADMINS:
        bot.answer_callback_query(c.id, "⛔ Нет доступа.")
        return
    admin_id = c.from_user.id
    start_admin_booking_flow_for_user(admin_id)
    bot.answer_callback_query(c.id, "Выберите дату.")

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_select_date:"))
def cb_admin_select_date(c: types.CallbackQuery):
    selected = c.data.split(":", 1)[1]
    day = datetime.fromisoformat(selected).date()
    admin_id = c.from_user.id

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

    user_states[admin_id] = {"step": "admin_select_time", "date": selected}
    bot.edit_message_text(f"Вы выбрали {day.strftime('%d.%m.%Y')}. Выберите время для клиента:", c.message.chat.id,
                          c.message.message_id, reply_markup=time_keyboard(slots, prefix="admin_book:"))

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_book:"))
def cb_admin_book(c: types.CallbackQuery):
    slot = c.data.split(":", 1)[1]
    admin_id = c.from_user.id
    state = user_states.get(admin_id)
    if not state or state.get("step") != "admin_select_time":
        bot.answer_callback_query(c.id, "Ошибка — начните процесс добавления клиента заново через меню.")
        return

    booking_date = state["date"]
    # check still free
    cur.execute("SELECT 1 FROM bookings WHERE booking_date=? AND booking_time=? AND status='booked'", (booking_date, slot))
    if cur.fetchone():
        bot.answer_callback_query(c.id, "Этот слот уже занят. Выберите другой.")
        return

    # store chosen time and ask for name
    user_states[admin_id].update({"step": "admin_enter_name", "time": slot})
    bot.send_message(admin_id, f"🧾 Введите имя клиента для записи на {booking_date} в {slot} (пример: Иван Иванов):")
    bot.answer_callback_query(c.id)

@bot.message_handler(func=lambda m: user_states.get(m.chat.id, {}).get("step") == "admin_enter_name")
def admin_enter_name(m: types.Message):
    admin_id = m.chat.id
    state = user_states.get(admin_id)
    if not state:
        bot.reply_to(m, "Ошибка состояния, начните заново через админ-меню.")
        return

    name = m.text.strip()
    if not name:
        bot.reply_to(m, "Имя не может быть пустым. Введите имя клиента:")
        return

    booking_date = state["date"]
    booking_time = state["time"]

    # generate unique negative user_id for offline client
    cur.execute("SELECT MIN(user_id) as min_uid FROM clients WHERE user_id < 0")
    row = cur.fetchone()
    if row and row["min_uid"] is not None:
        fake_user_id = row["min_uid"] - 1
    else:
        fake_user_id = -1

    # Insert offline client
    try:
        cur.execute("INSERT INTO clients(user_id, username, full_name, registered_at) VALUES(?, ?, ?, ?)",
                    (fake_user_id, "", name, datetime.now().isoformat()))
    except Exception:
        # in the unlikely event of a collision, find another id
        cur.execute("SELECT MIN(user_id) as min_uid FROM clients WHERE user_id < 0")
        row = cur.fetchone()
        if row and row["min_uid"] is not None:
            fake_user_id = row["min_uid"] - 1
        else:
            fake_user_id = -1
        cur.execute("INSERT INTO clients(user_id, username, full_name, registered_at) VALUES(?, ?, ?, ?)",
                    (fake_user_id, "", name, datetime.now().isoformat()))

    # create booking
    cur.execute("INSERT INTO bookings(client_id, booking_date, booking_time, status, created_at, reminder_sent) "
                "VALUES(?, ?, ?, 'booked', ?, 0)",
                (fake_user_id, booking_date, booking_time, datetime.now().isoformat()))
    conn.commit()
    booking_id = cur.lastrowid

    bot.send_message(admin_id, f"✅ Клиент <b>{name}</b> успешно записан на {booking_date} в {booking_time}. (ID записи: {booking_id}, клиент id: {fake_user_id})", parse_mode="HTML")

    # notify other admins
    for admin in ADMINS:
        if admin != admin_id:
            try:
                bot.send_message(admin, f"📅 Админ {m.from_user.first_name} добавил клиента {name} на {booking_date} в {booking_time}. (client_id: {fake_user_id})")
            except Exception:
                pass

    # clear state
    user_states.pop(admin_id, None)
