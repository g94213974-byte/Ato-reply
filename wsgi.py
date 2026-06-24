import sys
import os
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info("wsgi.py: Initializing...")

from main import flask_app, init_db, get_ai_bot, start_bot_async
from threading import Thread
from time import sleep

# Initialize database and AI bot
init_db()
logger.info("wsgi.py: Database initialized")

get_ai_bot()
logger.info("wsgi.py: AI Bot initialized")

# Start bot in background thread
logger.info("wsgi.py: Starting bot thread...")
bot_thread = Thread(target=start_bot_async, daemon=True)
bot_thread.start()
sleep(15)  # বট fully initialize হওয়ার জন্য অপেক্ষা
logger.info("wsgi.py: Bot thread started, gunicorn serving Flask...")

# Gunicorn will use 'flask_app' as the WSGI application
