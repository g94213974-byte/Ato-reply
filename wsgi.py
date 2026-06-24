import sys
import os
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

from main import flask_app, init_db, get_ai_bot, start_bot_async
from threading import Thread
from time import sleep

logger.info("wsgi.py: Initializing...")

try:
    init_db()
    logger.info("wsgi.py: Database initialized")
except Exception as e:
    logger.error(f"wsgi.py: DB init error: {e}")

try:
    get_ai_bot()
    logger.info("wsgi.py: AI Bot initialized")
except Exception as e:
    logger.error(f"wsgi.py: AI Bot error: {e}")

logger.info("wsgi.py: Starting bot thread...")
bot_thread = Thread(target=start_bot_async, daemon=True)
bot_thread.start()
logger.info("wsgi.py: Bot thread started, sleeping 10s...")
sleep(10)
logger.info("wsgi.py: Sleep done, returning app")

app = flask_app
