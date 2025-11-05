
from __future__ import annotations
import os
import sqlite3
import threading
import time
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
import telebot
from telebot import types

# ---------- Config ----------
load_dotenv()
TOKEN = os.getenv("TOKEN")
ADMINS = {int(x.strip()) for x in os.getenv("ADMINS", "").split(",") if x.strip()}

# Behaviour params
BOOKING_CUTOFF_HOURS = int(os.getenv("BOOKING_CUTOFF_HOURS", "1"))  # нельзя записаться ближе чем за N часов
REMINDER_HOURS_BEFORE = int(os.getenv("REMINDER_HOURS_BEFORE", "24"))  # напоминание за N часов
DATE_PICK_DAYS_AHEAD = int(os.getenv("DATE_PICK_DAYS_AHEAD", "7"))  # на сколько дней вперёд показывать даты
REMINDER_CHECK_INTERVAL = int(os.getenv("REMINDER_CHECK_INTERVAL", "600"))  # каждые N секунд проверять напоминания

if not TOKEN:
    raise SystemExit("ERROR: TOKEN is not set.")
if not ADMINS:
    raise SystemExit("ERROR: ADMINS is not set. Put admin user_id(s) to .env ADMINS as comma separated list.")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# ---------- Database ----------
DB_PATH = "hair_salon_bot.sqlite3"
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

# Create tables (initial schema includes fields we'll need).
cur.execute("""
CREATE TABLE IF NOT EXISTS clients (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    registered_at TEXT NOT NULL
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL,
    booking_date TEXT NOT NULL,  -- YYYY-MM-DD
    booking_time TEXT NOT NULL,  -- HH:MM
    status TEXT NOT NULL DEFAULT 'booked',  -- booked | canceled | done
    created_at TEXT NOT NULL,
    reminder_sent INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(client_id) REFERENCES clients(user_id)
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS day_offs (
    date TEXT PRIMARY KEY -- YYYY-MM-DD manual day off
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS weekday_offs (
    weekday INTEGER PRIMARY KEY -- 0=Monday ... 6=Sunday
)
""")

conn.commit()

# ---------- Ensure default weekday_offs (Monday off) ----------
# mark Monday (0) as weekly day off by default
cur.execute("INSERT OR IGNORE INTO weekday_offs(weekday) VALUES(?)", (0,))
conn.commit()

# ---------- FSM ----------
user_states: dict[int, dict[str, str]] = {}  # chat_id -> {"step": "...", ...}

# ---------- Helpers ----------
def ensure_client(user: types.User | int, username: str = "", full_name: str = ""):
    """
    Ensure client exists. `user` may be telegram user object or integer (user_id).
    If user is int and negative, it's an offline client.
    """
    uid = user.id if hasattr(user, "id") else user
    # For real telegram users, update their username/full_name each time they interact
    now = datetime.now().isoformat()
    cur.execute(
        "INSERT INTO clients(user_id, username, full_name, registered_at) VALUES(?, ?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name",
        (uid, username or (getattr(user, "username", "") if hasattr(user, "username") else ""),
         full_name or (f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip()), now))

    conn.commit()

def is_weekday_off(d: date) -> bool:
    cur.execute("SELECT 1 FROM weekday_offs WHERE weekday=?", (d.weekday(),))
    return cur.fetchone() is not None

def is_manual_day_off(d: date) -> bool:
    cur.execute("SELECT 1 FROM day_offs WHERE date=?", (d.isoformat(),))
    return cur.fetchone() is not None

def available_slots(day: date) -> list[str]:
    # Простая логика — рабочие часы: 9:00 - 18:00 каждый час (9..18 inclusive)
    slots = [f"{h:02d}:00" for h in range(9, 19)]
    cur.execute("SELECT booking_time FROM bookings WHERE booking_date=? AND status='booked'", (day.isoformat(),))
    booked = {row['booking_time'] for row in cur.fetchall()}
    # Применять cutoff: если day == today, убрать слоты которые ближе, чем BOOKING_CUTOFF_HOURS
    if day == date.today():
        now = datetime.now()
        cutoff_dt = now + timedelta(hours=BOOKING_CUTOFF_HOURS)
        allowed = []
        for s in slots:
            hh, mm = map(int, s.split(":"))
            slot_dt = datetime.combine(day, datetime.min.time()).replace(hour=hh, minute=mm)
            if slot_dt >= cutoff_dt:
                allowed.append(s)
        slots = allowed
    return [s for s in slots if s not in booked]

def date_keyboard(days_ahead: int = DATE_PICK_DAYS_AHEAD, prefix: str = "select_date:") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i in range(days_ahead):
        d = date.today() + timedelta(days=i)
        kb.add(types.InlineKeyboardButton(text=d.strftime("%d.%m.%Y"), callback_data=f"{prefix}{d.isoformat()}"))
    return kb

def time_keyboard(slots: list[str], prefix: str = "book:") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    for s in slots:
        kb.add(types.InlineKeyboardButton(text=s, callback_data=f"{prefix}{s}"))
    # add cancel button
    kb.add(types.InlineKeyboardButton(text="Отмена", callback_data="cancel_flow"))
    return kb

def fmt_booking_row(row: sqlite3.Row) -> str:
    return f"{row['booking_date']} в {row['booking_time']} — {row['full_name']} (@{row['username'] or '—'}) (id:{row['id']})"

# ---------- Bot Commands: Client ----------

# @bot.message_handler(commands=["start"])
# def cmd_start(m: types.Message):
#     # Ensure client exists (for real telegram users)
#     ensure_client(m.from_user)
#     bot.send_message(m.chat.id, f"👋 Привет, {m.from_user.first_name}!\n\nДоступные команды:")
#     show_main_menu(m.chat.id, m.from_user.id)

@bot.message_handler(commands=["start"])
def cmd_start(m: types.Message):
    ensure_client(m.from_user)
    # show active announcements briefly (we'll reuse announcements as a simple broadcast mechanism via /announce)
    bot.reply_to(m, "👋 Привет! Добро пожаловать.\n"
                    "Доступные команды:\n"
                    "/book — забронировать время\n"
                    "/mybookings — мои записи\n"
                    "/cancel — отменить запись\n")

@bot.message_handler(commands=["book"])
def cmd_book(m: types.Message):
    ensure_client(m.from_user)
    user_states[m.chat.id] = {"step": "select_date"}
    bot.send_message(m.chat.id, "Выберите дату для записи:", reply_markup=date_keyboard())

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
    bot.send_message(user.id, f"✅ Ваша запись: {day.strftime('%d.%m.%Y')} в {slot}. (ID {booking_id})")

    # notify admins
    for admin_id in ADMINS:
        try:
            bot.send_message(admin_id, f"📝 Новая запись: {user.first_name} {user.last_name or ''} (@{user.username or '—'})\n"
                                       f"Дата: {day.strftime('%d.%m.%Y')}\nВремя: {slot}\nID: {booking_id}")
        except Exception:
            pass

    user_states.pop(c.message.chat.id, None)


# ---------- Admin Menu Inline Keyboard ----------
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


# ---------- Главное меню ----------

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

# ---------- Admin Commands ----------
def admin_only(func):
    def wrapper(m: types.Message):
        if m.from_user.id not in ADMINS:
            bot.reply_to(m, "⛔ Нет доступа.")
            return
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

# ---------- Background tasks: reminders and cleanup ----------
def reminder_and_cleanup_loop():
    while True:
        try:
            now = datetime.now()
            # 1) Напоминания: найти брони, где reminder_sent=0 и время попадает в (now + REMINDER_HOURS_BEFORE) ± 30 минут
            window_start = now + timedelta(hours=REMINDER_HOURS_BEFORE)
            window_end = window_start + timedelta(minutes=59)  # целимся на интервал часа
            target_date = window_start.date().isoformat()
            cur.execute("SELECT b.id, b.booking_time, b.client_id, c.username FROM bookings b JOIN clients c ON b.client_id=c.user_id "
                        "WHERE b.booking_date=? AND b.status='booked' AND b.reminder_sent=0", (target_date,))
            rows = cur.fetchall()
            for r in rows:
                hh, mm = map(int, r["booking_time"].split(":"))
                booking_dt = datetime.combine(window_start.date(), datetime.min.time()).replace(hour=hh, minute=mm)
                if window_start <= booking_dt <= window_end:
                    # send reminder
                    try:
                        bot.send_message(r["client_id"], f"🔔 Напоминание: у вас запись через {REMINDER_HOURS_BEFORE} часов — {r['booking_time']} {target_date}.")
                    except Exception:
                        pass
                    # mark as sent
                    cur.execute("UPDATE bookings SET reminder_sent=1 WHERE id=?", (r["id"],))
                    conn.commit()

            # 2) Cleanup: пометить старые записи (прошедшие) как done (если статус booked и время < now - 1h)
            cutoff_time = now - timedelta(hours=1)
            cur.execute("SELECT id, booking_date, booking_time FROM bookings WHERE status='booked'")
            rows = cur.fetchall()
            for r in rows:
                bd = datetime.fromisoformat(r["booking_date"]).date()
                hh, mm = map(int, r["booking_time"].split(":"))
                booking_dt = datetime.combine(bd, datetime.min.time()).replace(hour=hh, minute=mm)
                if booking_dt < cutoff_time:
                    cur.execute("UPDATE bookings SET status='done' WHERE id=?", (r["id"],))
            conn.commit()
        except Exception:
            # swallow exceptions to keep loop alive
            pass
        time.sleep(REMINDER_CHECK_INTERVAL)

# Start background thread
t = threading.Thread(target=reminder_and_cleanup_loop, daemon=True)
t.start()

# ---------- Run Bot ----------
if __name__ == "__main__":
    print("Hair salon bot (with admin 'Add client' flow) is running...")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
