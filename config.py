import os

BOT_TOKEN = os.getenv("TOKEN")
DATABASE_PATH = os.getenv("DATABASE_PATH", "store.db")
if not os.path.isabs(DATABASE_PATH):
    DATABASE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), DATABASE_PATH))

ADMIN_IDS = [6098463726]
EGP_EXCHANGE_RATE = 55
PRICE_UNIT = int(os.getenv("PRICE_UNIT", "1000"))
# Whether to show user balance in EGP alongside USD in UI
SHOW_BALANCE_EGP = bool(int(os.getenv("SHOW_BALANCE_EGP", "1")))
