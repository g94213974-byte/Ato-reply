# config.py
import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "123456789"))

# Multiple accounts — define up to 10
# যে কয়টা দিবেন শুধু সেই কয়টা কাজ করবে (1-10)
ACCOUNTS = []

# Account 1
API_ID_1 = int(os.environ.get("API_ID_1", "0"))
API_HASH_1 = os.environ.get("API_HASH_1", "")
SESSION_1 = os.environ.get("SESSION_1", "")

# Account 2
API_ID_2 = int(os.environ.get("API_ID_2", "0"))
API_HASH_2 = os.environ.get("API_HASH_2", "")
SESSION_2 = os.environ.get("SESSION_2", "")

# Account 3
API_ID_3 = int(os.environ.get("API_ID_3", "0"))
API_HASH_3 = os.environ.get("API_HASH_3", "")
SESSION_3 = os.environ.get("SESSION_3", "")

# Account 4
API_ID_4 = int(os.environ.get("API_ID_4", "0"))
API_HASH_4 = os.environ.get("API_HASH_4", "")
SESSION_4 = os.environ.get("SESSION_4", "")

# Account 5
API_ID_5 = int(os.environ.get("API_ID_5", "0"))
API_HASH_5 = os.environ.get("API_HASH_5", "")
SESSION_5 = os.environ.get("SESSION_5", "")

# Account 6
API_ID_6 = int(os.environ.get("API_ID_6", "0"))
API_HASH_6 = os.environ.get("API_HASH_6", "")
SESSION_6 = os.environ.get("SESSION_6", "")

# Account 7
API_ID_7 = int(os.environ.get("API_ID_7", "0"))
API_HASH_7 = os.environ.get("API_HASH_7", "")
SESSION_7 = os.environ.get("SESSION_7", "")

# Account 8
API_ID_8 = int(os.environ.get("API_ID_8", "0"))
API_HASH_8 = os.environ.get("API_HASH_8", "")
SESSION_8 = os.environ.get("SESSION_8", "")

# Account 9
API_ID_9 = int(os.environ.get("API_ID_9", "0"))
API_HASH_9 = os.environ.get("API_HASH_9", "")
SESSION_9 = os.environ.get("SESSION_9", "")

# Account 10
API_ID_10 = int(os.environ.get("API_ID_10", "0"))
API_HASH_10 = os.environ.get("API_HASH_10", "")
SESSION_10 = os.environ.get("SESSION_10", "")

# Auto-build accounts list (only non-empty ones)
for i in range(1, 11):
    api_id = locals().get(f"API_ID_{i}")
    api_hash = locals().get(f"API_HASH_{i}")
    session = locals().get(f"SESSION_{i}")
    
    # শুধু যদি API_ID > 0 এবং Session খালি না হয় তাহলে যোগ করবে
    if api_id and api_id > 0 and session and session.strip():
        ACCOUNTS.append({
            'api_id': api_id,
            'api_hash': api_hash,
            'session': session.strip()
        })
