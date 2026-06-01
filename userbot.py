import os
import asyncio
from telethon import TelegramClient

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

if not API_ID or not API_HASH:
    print("Missing API_ID or API_HASH")
    exit()

API_ID = int(API_ID)

sessions = [
    os.getenv("SESSION_1"),
    os.getenv("SESSION_2"),
    os.getenv("SESSION_3")
]

clients = []

async def start_client(session):
    try:
        if not session:
            return None

        client = TelegramClient(session, API_ID, API_HASH)
        await client.start()
        print("Client started")
        return client

    except Exception as e:
        print("Client error:", e)
        return None

async def main():

    for s in sessions:
        c = await start_client(s)
        if c:
            clients.append(c)

    if not clients:
        print("No valid sessions")
        return

    print("Bot running...")

    await asyncio.gather(
        *[c.run_until_disconnected() for c in clients]
    )

asyncio.run(main())
