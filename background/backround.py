from datetime import datetime, timedelta
import time
from bot_in import bot
from database import cur,conn
from config.config import REMINDER_HOURS_BEFORE,REMINDER_CHECK_INTERVAL

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
