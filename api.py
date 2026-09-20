from flask import Flask, jsonify, request, send_from_directory
from database import cur, conn
from datetime import date, timedelta, datetime

app = Flask(__name__)


# добавь в начало после imports
@app.route("/")
def index():
    return send_from_directory("webapp", "index.html")

@app.after_request
def add_headers(response):
    response.headers["ngrok-skip-browser-warning"] = "true"
    return response


# --- Клиент: получить свободные слоты ---
@app.route("/api/slots")
def get_slots():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "date required"}), 400

    try:
        day = date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "invalid date"}), 400

    # занятые слоты
    cur.execute(
        "SELECT booking_time FROM bookings WHERE booking_date=? AND status='booked'",
        (date_str,)
    )
    booked = {row[0] for row in cur.fetchall()}

    # все слоты
    slots = []
    cur_time = datetime.combine(day, datetime.min.time()).replace(hour=9, minute=0)
    end = datetime.combine(day, datetime.min.time()).replace(hour=18, minute=0)
    while cur_time <= end:
        t = cur_time.strftime("%H:%M")
        slots.append({"time": t, "free": t not in booked})
        cur_time += timedelta(minutes=30)

    return jsonify({"date": date_str, "slots": slots})


# --- Админ: записи на день ---
@app.route("/api/admin/bookings")
def get_bookings():
    date_str = request.args.get("date", date.today().isoformat())
    cur.execute("""
        SELECT b.id, b.booking_time, c.full_name
        FROM bookings b
        JOIN clients c ON b.client_id = c.user_id
        WHERE b.booking_date = ? AND b.status = 'booked'
        ORDER BY b.booking_time
    """, (date_str,))
    rows = cur.fetchall()
    return jsonify({
        "date": date_str,
        "bookings": [{"id": r[0], "time": r[1], "name": r[2]} for r in rows]
    })


# --- Админ: все клиенты ---
@app.route("/api/admin/clients")
def get_clients():
    cur.execute("SELECT user_id, username, full_name, registered_at FROM clients ORDER BY registered_at DESC")
    rows = cur.fetchall()
    return jsonify({
        "clients": [{"id": r[0], "username": r[1], "name": r[2], "registered_at": r[3]} for r in rows]
    })


# --- Записаться ---
@app.route("/api/book", methods=["POST"])
def book():
    data = request.json
    user_id = data.get("user_id")
    date_str = data.get("date")
    time_str = data.get("time")

    if not all([user_id, date_str, time_str]):
        return jsonify({"ok": False, "error": "Не хватает данных"}), 400

    # проверяем что слот свободен
    cur.execute(
        "SELECT 1 FROM bookings WHERE booking_date=? AND booking_time=? AND status='booked'",
        (date_str, time_str)
    )
    if cur.fetchone():
        return jsonify({"ok": False, "error": "Слот уже занят"})

    cur.execute("""
        INSERT INTO bookings(client_id, booking_date, booking_time, status, created_at, reminder_sent)
        VALUES(?, ?, ?, 'booked', ?, 0)
    """, (user_id, date_str, time_str, datetime.now().isoformat()))
    conn.commit()
    return jsonify({"ok": True})

# --- Мои записи ---
@app.route("/api/my_bookings")
def my_bookings():
    user_id = request.args.get("user_id")
    cur.execute(
        "SELECT id, booking_date, booking_time FROM bookings WHERE client_id=? AND status='booked' ORDER BY booking_date, booking_time",
        (user_id,)
    )
    rows = cur.fetchall()
    return jsonify({"bookings": [{"id": r[0], "date": r[1], "time": r[2]} for r in rows]})

# --- Отменить запись ---
@app.route("/api/cancel", methods=["POST"])
def cancel():
    data = request.json
    booking_id = data.get("booking_id")
    cur.execute("UPDATE bookings SET status='canceled' WHERE id=?", (booking_id,))
    conn.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(port=5000, debug=True)