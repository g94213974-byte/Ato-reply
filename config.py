import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 0))
USER_API_ID = int(os.environ.get("USER_API_ID", 0))
USER_API_HASH = os.environ.get("USER_API_HASH", "")
USER_STRING_SESSION = os.environ.get("USER_STRING_SESSION", "")

DB_FILE = "userbot.db"
