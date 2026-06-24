import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from main import flask_app, init_db, get_ai_bot, start_bot_async
from threading import Thread
from time import sleep

# Initialize everything on import
init_db()
get_ai_bot()

# Start bot in background
bot_thread = Thread(target=start_bot_async, daemon=True)
bot_thread.start()
sleep(5)

app = flask_app
