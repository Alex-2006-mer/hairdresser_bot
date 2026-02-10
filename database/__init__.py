import sqlite3
from datetime import datetime, date, timedelta
from telebot import types
from config import BOOKING_CUTOFF_HOURS,DATE_PICK_DAYS_AHEAD

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


messages = {}

def send_clean_message(bot, chat_id, text, reply_markup=None):
    # Удаляем предыдущие сообщения бота
    if chat_id in messages:
        for msg_id in messages[chat_id]:
            try:
                bot.delete_message(chat_id, msg_id)
            except Exception:
                pass

    # Отправляем новое сообщение
    sent = bot.send_message(chat_id, text, reply_markup=reply_markup)
    messages[chat_id] = [sent.message_id]



# ----------------- Время по пол часа -----------------------
def available_slots(day: date) -> list[str]:
    # Генерация слотов каждые 30 минут с 9:00 до 18:00
    slots = []
    start = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=0)
    end = datetime.combine(day, datetime.min.time()).replace(hour=18, minute=0)

    cur_time = start
    while cur_time <= end:
        slots.append(cur_time.strftime("%H:%M"))
        cur_time += timedelta(minutes=30)

    # Получить занятые слоты
    cur.execute(
        "SELECT booking_time FROM bookings WHERE booking_date=? AND status='booked'",
        (day.isoformat(),)
    )
    booked = {row['booking_time'] for row in cur.fetchall()}

    # Применение cutoff: нельзя записываться раньше чем через BOOKING_CUTOFF_HOURS сегодня
    if day == date.today():
        now = datetime.now()
        cutoff_dt = now + timedelta(hours=BOOKING_CUTOFF_HOURS)
        slots = [s for s in slots if datetime.combine(day, datetime.strptime(s, "%H:%M").time()) >= cutoff_dt]

    # Убираем занятые
    return [s for s in slots if s not in booked]

# ------------- Создание кнопки 7 дней недели ---------------------------------
def date_keyboard(days_ahead: int = DATE_PICK_DAYS_AHEAD, prefix: str = "select_date:") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    for i in range(days_ahead):
        d = date.today() + timedelta(days=i)
        kb.add(types.InlineKeyboardButton(text=d.strftime("%d.%m.%Y"), callback_data=f"{prefix}{d.isoformat()}"))
    return kb
# --------------
def time_keyboard(slots: list[str], prefix: str = "book:") -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=3)
    for s in slots:
        kb.add(types.InlineKeyboardButton(text=s, callback_data=f"{prefix}{s}"))
    # add cancel button
    kb.add(types.InlineKeyboardButton(text="Отмена", callback_data="cancel_flow"))
    return kb

def fmt_booking_row(row: sqlite3.Row) -> str:
    return f"{row['booking_date']} в {row['booking_time']} — {row['full_name']} (@{row['username'] or '—'}) (id:{row['id']})"
