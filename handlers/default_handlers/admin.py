from telebot import types
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from bot_in import bot
from config.config import ADMINS
from datetime import datetime, timedelta
from database import cur,conn, user_states,time_keyboard, date_keyboard, is_weekday_off,is_manual_day_off,available_slots

@bot.message_handler(commands=["menu"])
def admin_menu(m: types.Message):
    if m.from_user.id not in ADMINS:
        bot.reply_to(m, "⛔ Нет доступа.")
        return

    k_1 = InlineKeyboardButton(text="📅 День выходной", callback_data="dayoff")
    k_2 = InlineKeyboardButton(text="✅ Открыть день", callback_data="openday")
    k_3 = InlineKeyboardButton(text="🗑 Удалить запись", callback_data="delbooking")
    k_4 = InlineKeyboardButton(text="Клиенты", callback_data="clients")
    k_5 = InlineKeyboardButton(text="📅 Записи", callback_data="show_bookings")  # ✅ новая кнопка

    keyboard_3 = InlineKeyboardMarkup()
    keyboard_3.add(k_1, k_2, k_3, k_4, k_5)

    bot.send_message(m.chat.id, "⚙️ Меню администратора:", reply_markup=keyboard_3)  # ✅


@bot.callback_query_handler(func=lambda c: c.data == "show_bookings")
def cb_show_bookings(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.answer_callback_query(c.id, "⛔ Нет доступа.")
        return

    # показываем даты на которые есть записи + ближайшие 7 дней
    from datetime import date, timedelta
    kb = InlineKeyboardMarkup()

    today = date.today()
    for i in range(7):
        d = today + timedelta(days=i)
        # считаем записи на этот день
        cur.execute(
            "SELECT COUNT(*) FROM bookings WHERE booking_date=? AND status='booked'",
            (d.isoformat(),)
        )
        count = cur.fetchone()[0]

        label = d.strftime("%d.%m.%Y")
        if i == 0:
            label = f"Сегодня {label}"
        elif i == 1:
            label = f"Завтра {label}"

        # показываем количество записей на кнопке
        label += f" ({count} зап.)"

        kb.add(InlineKeyboardButton(
            text=label,
            callback_data=f"admin_day:{d.isoformat()}"
        ))

    bot.edit_message_text(
        "📅 Выберите день:",
        c.message.chat.id,
        c.message.message_id,
        reply_markup=kb
    )
    bot.answer_callback_query(c.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_day:"))
def cb_admin_day(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.answer_callback_query(c.id, "⛔ Нет доступа.")
        return

    from datetime import datetime, date
    selected = c.data.split(":")[1]
    day = date.fromisoformat(selected)

    # получаем все занятые слоты
    cur.execute("""
        SELECT b.booking_time, c.full_name
        FROM bookings b
        JOIN clients c ON b.client_id = c.user_id
        WHERE b.booking_date = ? AND b.status = 'booked'
        ORDER BY b.booking_time
    """, (selected,))
    booked_rows = cur.fetchall()
    booked_dict = {row[0]: row[1] for row in booked_rows}

    # генерируем все слоты с 9:00 до 18:00
    from datetime import timedelta
    all_slots = []
    start = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=0)
    end = datetime.combine(day, datetime.min.time()).replace(hour=18, minute=0)
    cur_time = start
    while cur_time <= end:
        all_slots.append(cur_time.strftime("%H:%M"))
        cur_time += timedelta(minutes=30)

    # формируем текст
    text = f"📅 Записи на {day.strftime('%d.%m.%Y')}:\n\n"

    booked_count = 0
    free_count = 0

    for slot in all_slots:
        if slot in booked_dict:
            text += f"🔴 {slot} — {booked_dict[slot]}\n"
            booked_count += 1
        else:
            text += f"🟢 {slot} — свободно\n"
            free_count += 1

    text += f"\n 🔴 Занято: {booked_count} | 🟢 Свободно: {free_count}"

    # кнопка назад
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(text="◀️ Назад", callback_data="show_bookings"))

    bot.edit_message_text(
        text,
        c.message.chat.id,
        c.message.message_id,
        reply_markup=kb
    )
    bot.answer_callback_query(c.id)

@bot.message_handler(func=lambda m: m.text == "📅 Записи")
def show_dates(m):
    if m.from_user.id not in ADMINS:
        bot.send_message(m.chat.id, "⛔ Нет доступа")
        return

    kb = types.InlineKeyboardMarkup()

    # Получаем уникальные даты из базы
    cur.execute("SELECT DISTINCT booking_date FROM bookings")
    dates = cur.fetchall()

    if not dates:
        bot.send_message(m.chat.id, "Записей пока нет.")
        return

    for d in dates:
        date_value = d[0]  # первая колонка результата

        kb.add(types.InlineKeyboardButton(
            text=date_value,
            callback_data=f"admin_date_2:{date_value}"
        ))

    bot.send_message(m.chat.id, "Выберите дату:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_date_2:"))
def show_day_appointments(c):
    if c.from_user.id not in ADMINS:
        bot.answer_callback_query(c.id, "Нет доступа")
        return

    selected_date = c.data.split(":")[1]

    cur.execute("""
    SELECT c.full_name, b.booking_time
    FROM bookings b
    JOIN clients c ON b.client_id = c.user_id
    WHERE b.booking_date = ?
    ORDER BY b.booking_time
    """, (selected_date,))
    rows = cur.fetchall()

    if not rows:
        bot.edit_message_text(
            "На этот день записей нет.",
            c.message.chat.id,
            c.message.message_id
        )
        return

    text = f"📅 Записи на {selected_date}:\n\n"

    for row in rows:
        text += f"{row[1]} — {row[0]}\n"

    bot.edit_message_text(
        text,
        c.message.chat.id,
        c.message.message_id
    )

@bot.callback_query_handler(func=lambda c: c.data == "dayoff")
def cmd_dayoff(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.send_message(c.message.chat.id, "⛔ Нет доступа.")
        return
    msg = bot.send_message(c.message.chat.id, "Введите дату выходного в формате YYYY-MM-DD:")
    bot.register_next_step_handler(msg, save_dayoff)

def save_dayoff(message):
    try:
            day = datetime.fromisoformat(message.text).date()
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат. Попробуйте еще раз: YYYY-MM-DD")
        return
    cur.execute("INSERT OR IGNORE INTO day_offs(date) VALUES(?)", (day.isoformat(),))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ {day.strftime('%d.%m.%Y')} отмечен как выходной.")
# --------------------------------------------------------------------
@bot.callback_query_handler(func=lambda c: c.data == "openday")
def cmd_openday(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.send_message(c.message.chat.id, "⛔ Нет доступа.")
        return
    msg = bot.send_message(c.message.chat.id, "Введите дату рабочего в формате YYYY-MM-DD:")
    bot.register_next_step_handler(msg, save_openday)

def save_openday(message):
    try:
            day = datetime.fromisoformat(message.text).date()
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат. Попробуйте еще раз: YYYY-MM-DD")
        return
    cur.execute("DELETE FROM day_offs WHERE date=?", (day.isoformat(),))
    conn.commit()
    bot.send_message(message.chat.id,f"✅ {day.strftime('%d.%m.%Y')} снова открыт для записи.")

@bot.callback_query_handler(func=lambda c: c.data == "clients")
def cb_clients(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.send_message(c.message.chat.id, "⛔ Нет доступа.")
        return

    try:
        cur.execute("""
            SELECT user_id, username, full_name, registered_at 
            FROM clients 
            ORDER BY registered_at DESC
        """)
        rows = cur.fetchall()

        if not rows:
            bot.send_message(c.message.chat.id, "Нет клиентов.")
            return

        text = "👥 Клиенты:\n\n" + "\n".join([
            f"{r['full_name']} --> (@{r['username']})\n---------------------------------------------"
            for r in rows
        ])

        # Telegram лимит ~4096 символов
        for i in range(0, len(text), 4000):
            bot.send_message(c.message.chat.id, text[i:i+4000])

    except Exception as e:
        bot.send_message(c.message.chat.id, "Ошибка при получении списка клиентов.")


@bot.callback_query_handler(func=lambda c: c.data == "delbooking")
def cb_delbooking(c: types.CallbackQuery):
    if c.from_user.id not in ADMINS:
        bot.send_message(c.message.chat.id, "⛔ Нет доступа.")
        return
    msg = bot.send_message(c.message.chat.id, "Введите ID записи для удаления:")
    bot.register_next_step_handler(msg, process_delbooking)
def process_delbooking(message: types.Message):
    if message.from_user.id not in ADMINS:
        return
    try:
        booking_id = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ Нужно ввести число ID.")
        return

    cur.execute(
        "SELECT client_id, booking_date, booking_time FROM bookings WHERE id=?",
        (booking_id,))
    row = cur.fetchone()
    if not row:
        bot.send_message(message.chat.id, f"Запись с ID {booking_id} не найдена.")
        return
    cur.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
    conn.commit()
    bot.send_message(message.chat.id, f"✅ Запись {booking_id} удалена.")
    try:
        bot.send_message(
            row["client_id"],
            f"❌ Ваша запись на {row['booking_date']} в {row['booking_time']} была удалена администратором.")
    except Exception:
        pass


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


def start_admin_booking_flow(c: types.CallbackQuery):
    """Start the admin flow for manually adding a client booking (offline client)."""
    if c.from_user.id not in ADMINS:
        bot.answer_callback_query(c.id, "⛔ Нет доступа.")
        return

    admin_id = c.from_user.id
    # store state keyed by admin chat id
    user_states[admin_id] = {"step": "admin_select_date"}
    # send date keyboard but with admin-specific callback prefix
    bot.send_message(admin_id, "📅 Выберите дату для записи клиента:", reply_markup=date_keyboard(prefix="admin_select_date:"))
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
