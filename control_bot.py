import json
from telethon import TelegramClient, events, Button

API_ID = 123
API_HASH = "xxx"
BOT_TOKEN = "xxx"

bot = TelegramClient("bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

def load():
    return json.load(open("database.json"))

def save(data):
    json.dump(data, open("database.json","w"), indent=4)

# -------- MENU --------
def menu():
    return [
        [Button.inline("🤖 Bot ON/OFF", b"bot")],
        [Button.inline("➕ Add Account", b"addacc")],
        [Button.inline("📝 Edit Reply", b"edit")],
        [Button.inline("🖼 Welcome Edit", b"welcome")],
        [Button.inline("🤖 Gemini ON/OFF", b"gemini")],
        [Button.inline("📊 Status", b"status")]
    ]

# -------- START --------
@bot.on(events.NewMessage(pattern="/start"))
async def start(event):
    await event.reply("Control Panel", buttons=menu())

# -------- CALLBACKS --------
@bot.on(events.CallbackQuery)
async def cb(event):

    data = load()

    if event.data == b"bot":
        data["bot_on"] = not data["bot_on"]
        save(data)
        await event.answer(f"Bot: {data['bot_on']}")

    elif event.data == b"gemini":
        data["gemini_on"] = not data["gemini_on"]
        save(data)
        await event.answer(f"Gemini: {data['gemini_on']}")

    elif event.data == b"status":
        await event.edit(
            f"BOT: {data['bot_on']}\n"
            f"GEMINI: {data['gemini_on']}\n"
            f"USAGE: {data['gemini_used']}/{data['gemini_limit']}"
        )

bot.run_until_disconnected()
