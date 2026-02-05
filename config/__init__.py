import os
from dotenv import load_dotenv

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

