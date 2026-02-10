from __future__ import annotations

import threading
import time

from telebot.apihelper import ApiTelegramException

import handlers.default_handlers.admin  # noqa: F401 (register handlers)
import handlers.default_handlers.booking  # noqa: F401 (register handlers)
import handlers.default_handlers.start  # noqa: F401 (register handlers)
from background import reminder_and_cleanup_loop
from bot_in import bot


def run_polling_forever() -> None:
    """Run bot polling with retry on Telegram API conflicts/intermittent errors."""
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30)
        except ApiTelegramException as e:
            # 409: another process is already calling getUpdates with same token.
            # Keep process alive and retry after delay instead of hard crash.
            if "Error code: 409" in str(e) or "terminated by other getUpdates request" in str(e):
                print("[WARN] Telegram API conflict (409): another bot instance is running. Retry in 5s...")
                time.sleep(5)
                continue
            print(f"[ERROR] Telegram API exception: {e}. Retry in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}. Retry in 5s...")
            time.sleep(5)


if __name__ == "__main__":
    t = threading.Thread(target=reminder_and_cleanup_loop, daemon=True)
    t.start()

    print("Hair salon bot (with admin 'Add client' flow) is running...")
    run_polling_forever()
