import sys
import os
import logging

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info("=" * 50)
logger.info("WSGI: Loading application...")
logger.info("=" * 50)

try:
    from main import flask_app, init_db, get_ai_bot, start_bot_async
    from threading import Thread
    from time import sleep
    
    logger.info("WSGI: Imports successful")
    
    init_db()
    logger.info("WSGI: Database initialized")
    
    get_ai_bot()
    logger.info("WSGI: AI Bot initialized")
    
    logger.info("WSGI: Starting bot thread...")
    bot_thread = Thread(target=start_bot_async, daemon=True)
    bot_thread.start()
    logger.info("WSGI: Bot thread started, waiting 10 seconds...")
    sleep(10)
    logger.info("WSGI: Setup complete, returning Flask app")
    
    app = flask_app
    
except Exception as e:
    logger.error(f"WSGI: Critical error: {e}", exc_info=True)
    from main import flask_app
    app = flask_app
    logger.warning("WSGI: Running Flask only (no bot)")
