import os
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

print("Script started")

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

print("API_ID:", API_ID)
print("API_HASH exists:", bool(API_HASH))

if not API_ID or not API_HASH:
    print("Missing API_ID or API_HASH")
    raise SystemExit(1)

API_ID = int(API_ID)

sessions = [
    os.getenv("SESSION_1"),
    os.getenv("SESSION_2"),
    os.getenv("SESSION_3")
]

print("Sessions loaded:", [bool(s) for s in sessions])

clients = []

async def start_client(session, num):
    try:
        if not session:
            print(f"SESSION_{num} missing")
            return None

        print(f"Starting SESSION_{num}")

        client = TelegramClient(
            StringSession(session),
            API_ID,
            API_HASH
        )

        await client.start()

        me = await client.get_me()
        print(f"SESSION_{num} connected: {me.id}")

        return client

    except Exception as e:
        print(f"SESSION_{num} error:", repr(e))
        return None

async def main():
    print("Main started")

    for i, s in enumerate(sessions, start=1):
        c = await start_client(s, i)

        if c:
            clients.append(c)

    print("Valid clients:", len(clients))

    if not clients:
        print("No valid sessions")

        while True:
            await asyncio.sleep(60)

    print("Bot running...")

    await asyncio.gather(
        *[c.run_until_disconnected() for c in clients]
    )

asyncio.run(main())
