from __future__ import annotations
import handlers.default_handlers.booking  # noqa: F401 (register handlers)
import handlers.default_handlers.admin  # noqa: F401 (register handlers)
import handlers.default_handlers.start  # noqa: F401 (register handlers)
from background import reminder_and_cleanup_loop
import threading
from bot_in import bot

t = threading.Thread(target=reminder_and_cleanup_loop, daemon=True)
t.start()

if __name__ == "__main__":
    print("Hair salon bot (with admin 'Add client' flow) is running...")
    bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
