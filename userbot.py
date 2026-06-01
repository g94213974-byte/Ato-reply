import json, asyncio, time
from telethon import TelegramClient, events

def load(file):
    return json.load(open(file))

db = load("database.json")
replies = load("replies.json")

clients = []
sent = set()

# -------- LOAD ACCOUNTS --------
for acc in db["accounts"]:
    client = TelegramClient(acc["session"], acc["api_id"], acc["api_hash"])
    clients.append(client)

# -------- SPAM CONTROL --------
last_msg = {}

def is_spam(uid):
    now = time.time()
    if uid in last_msg and now - last_msg[uid] < 3:
        return True
    last_msg[uid] = now
    return False

# -------- HANDLER --------
def register(client):

    @client.on(events.NewMessage(incoming=True))
    async def handler(event):

        if not event.is_private:
            return

        uid = event.sender_id
        msg = event.raw_text.lower()

        # BOT OFF
        if not db["bot_on"]:
            return

        # SPAM CHECK
        if is_spam(uid):
            return

        # WELCOME
        if uid not in sent:
            sent.add(uid)
            await client.send_file(
                event.chat_id,
                db["welcome_photo"],
                caption=db["welcome_text"]
            )
            return

        async with client.action(event.chat_id, "typing"):
            await asyncio.sleep(3)

            # CUSTOM REPLY
            for k, v in replies.items():
                if k in msg:
                    await event.reply(v)
                    return

            # GEMINI OFF → DEFAULT
            await event.reply("Pay and come baby")

# -------- START --------
async def main():
    for c in clients:
        register(c)
        await c.start()

    await asyncio.gather(*[c.run_until_disconnected() for c in clients])

asyncio.run(main())
