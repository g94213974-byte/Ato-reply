import asyncio
import os
import time
import logging
from threading import Thread

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.types import MessageMediaPhoto

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count
from config import BOT_TOKEN, ADMIN_ID, USER_API_ID, USER_API_HASH, USER_STRING_SESSION

# ===== Logger =====
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ===== Flask =====
flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "running"})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

# ===== User Account =====
user_client = None
user_bot_running = False
user_account_info = None  # ✅ নতুন যোগ: account info রাখার জন্য

async def start_user_client():
    global user_client, user_bot_running, user_account_info
    try:
        user_client = TelegramClient(StringSession(USER_STRING_SESSION), USER_API_ID, USER_API_HASH)
        await user_client.start()
        me = await user_client.get_me()
        user_account_info = me  # ✅ account info save
        logger.info(f"✅ User Account: {me.first_name} (ID: {me.id})")
        user_bot_running = True

        from telethon import events

        @user_client.on(events.NewMessage(incoming=True))
        async def auto_reply_handler(event):
            if not event.is_private:
                return

            sender = await event.get_sender()
            sender_id = sender.id

            if sender_id == ADMIN_ID:
                return

            # ✅ SEEN (ডাবল টিক) - message পড়া হয়েছে বলে mark করে দেয়
            try:
                await user_client.send_read_acknowledge(event.message)
            except:
                pass

            # ✅ ANTI-SPAM সরিয়ে দেওয়া হয়েছে (পুরো block টা delete)

            # Block photo
            if event.message.media and isinstance(event.message.media, MessageMediaPhoto):
                if get_setting('block_photo_enabled', '1') == '1':
                    try:
                        await user_client(BlockRequest(id=sender_id))
                    except:
                        pass
                    return

            # Typing time
            typing_enabled = get_setting('typing_enabled', '1') == '1'
            typing_duration = int(get_setting('typing_duration', '5'))  # ✅ ডিফল্ট 5 সেকেন্ড

            msg_text = event.message.text or ""
            msg_lower = msg_text.lower().strip()

            # ===== CHECK REPLIES (keyword match) =====
            replies = get_all_replies()
            matched = False

            for rid, keyword, reply_text, rtype in replies:
                kw = keyword.lower().strip()
                if rtype == "exact" and msg_lower == kw:
                    matched = True
                    if typing_enabled:
                        async with user_client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    await event.respond(reply_text)
                    break
                elif rtype == "contains" and kw in msg_lower:
                    matched = True
                    if typing_enabled:
                        async with user_client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    await event.respond(reply_text)
                    break

            # ===== NO MATCH =====
            if not matched:
                welcome_enabled = get_setting('welcome_enabled', '1') == '1'
                
                if welcome_enabled:
                    if typing_enabled:
                        async with user_client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    
                    welcome_msg = get_setting('welcome_message', '👋 Welcome!')
                    welcome_photo = get_setting('welcome_photo', '')
                    if welcome_photo:
                        try:
                            await user_client.send_file(sender_id, welcome_photo, caption=welcome_msg)
                        except:
                            await event.respond(welcome_msg)
                    else:
                        await event.respond(welcome_msg)
                
                else:
                    default_reply_enabled = get_setting('default_reply_enabled', '1') == '1'
                    if default_reply_enabled:
                        if typing_enabled:
                            async with user_client.action(event.chat_id, "typing"):
                                await asyncio.sleep(typing_duration)
                        
                        default_reply = get_setting('default_reply_text', 
                            '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি। দয়া করে সঠিকভাবে লিখুন।')
                        await event.respond(default_reply)

        # ✅ run_until_disconnected ব্যবহার না করে ping রাখা
        while True:
            try:
                await asyncio.sleep(30)
                me = await user_client.get_me()
                if me:
                    logger.debug(f"User client alive: {me.first_name}")
            except:
                logger.warning("User client ping failed")
                user_bot_running = False
                break

    except Exception as e:
        logger.error(f"User account error: {e}")
        user_bot_running = False


# ====================================================
#    BOT COMMANDS + LOGIN (শুধু বাটন)
# ====================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_info = ""
    if user_account_info:
        user_info = f"👤 Account: {user_account_info.first_name} (ID: {user_account_info.id})"
    
    keyboard = [
        [InlineKeyboardButton("📋 Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("➕ Add Reply", callback_data="menu_add_reply")],
        [InlineKeyboardButton("🗑 Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
        [InlineKeyboardButton("🔐 Login New Account", callback_data="menu_login")]  # ✅ নতুন বাটন
    ]
    text = (
        "🤖 **UserBot Control Panel**\n\n"
        f"🟢 UserBot: {'✅ Running' if user_bot_running else '❌ Stopped'}\n"
        f"📝 Total Replies: {get_reply_count()}\n"
        f"{user_info}\n\n"
        "নিচের বাটন ক্লিক করুন 👇"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


# ===== Callback Handlers =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data

    # ===== MAIN MENU =====
    if data == "main_menu":
        await show_main_menu(update, context)

    # ===== ✅ LOGIN NEW ACCOUNT =====
    elif data == "menu_login":
        await query.edit_message_text(
            "🔐 **Login New Account - Step 1/3**\n\n"
            "আপনার **API ID** লিখুন (শুধু সংখ্যা):\n\n"
            "বাতিল করতে `/cancel` টাইপ করুন",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'login_api_id'

    # ===== REPLIES LIST =====
    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 **No replies yet!**\n\n+ Add Reply বাটনে ক্লিক করুন।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]),
                parse_mode='Markdown'
            )
            return

        page = int(context.user_data.get('reply_page', 0))
        items_per_page = 5
        total_pages = (len(replies) + items_per_page - 1) // items_per_page
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_replies = replies[start_idx:end_idx]

        msg = f"📋 **Replies (Page {page+1}/{total_pages})**\n\n"
        for r in page_replies:
            rid, keyword, reply_text, rtype = r
            emoji = "🔑" if rtype == "exact" else "🔍"
            msg += f"{emoji} `ID:{rid}` | `{keyword[:20]}`\n   ➜ {reply_text[:40]}...\n\n"

        keyboard = []
        nav_btns = []
        if page > 0:
            nav_btns.append(InlineKeyboardButton("◀️ Prev", callback_data=f"reply_page_{page-1}"))
        if page < total_pages - 1:
            nav_btns.append(InlineKeyboardButton("Next ▶️", callback_data=f"reply_page_{page+1}"))
        if nav_btns:
            keyboard.append(nav_btns)
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    elif data.startswith("reply_page_"):
        context.user_data['reply_page'] = int(data.split("_")[2])
        await button_callback(update, context)

    # ===== ADD REPLY =====
    elif data == "menu_add_reply":
        await query.edit_message_text(
            "➕ **Add Reply - Step 1/3**\n\n"
            "✅ *Exact Match:* Keyword হুবহু মিললে reply দিবে\n"
            "🔍 *Contains:* Keyword থাকলেই reply দিবে\n\n"
            "**কীওয়ার্ড টি লিখুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'keyword'

    elif data == "reply_type_exact":
        context.user_data['reply_type'] = 'exact'
        await query.edit_message_text(
            "➕ **Add Reply - Step 3/3**\n\n"
            f"🔑 Keyword: `{context.user_data.get('add_keyword', '')}`\n"
            f"🏷️ Type: `Exact Match`\n\n"
            "**রিপ্লাই টেক্সট লিখুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'reply_text'

    elif data == "reply_type_contains":
        context.user_data['reply_type'] = 'contains'
        await query.edit_message_text(
            "➕ **Add Reply - Step 3/3**\n\n"
            f"🔑 Keyword: `{context.user_data.get('add_keyword', '')}`\n"
            f"🏷️ Type: `Contains`\n\n"
            "**রিপ্লাই টেক্সট লিখুন:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'reply_text'

    # ===== DELETE REPLY =====
    elif data == "menu_del_reply":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 **No replies to delete!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
            )
            return

        keyboard = []
        for r in replies[:10]:
            rid, keyword, _, rtype = r
            emoji = "🔑" if rtype == "exact" else "🔍"
            keyboard.append([InlineKeyboardButton(f"{emoji} ID:{rid} - {keyword[:25]}", callback_data=f"confirm_del_{rid}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])

        await query.edit_message_text(
            "🗑 **Delete Reply**\n\nযেটা ডিলিট করতে চান সেটিতে ক্লিক করুন:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    elif data.startswith("confirm_del_"):
        rid = int(data.split("_")[2])
        keyboard = [
            [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"do_delete_{rid}")],
            [InlineKeyboardButton("❌ No, Cancel", callback_data="menu_del_reply")]
        ]
        await query.edit_message_text(
            f"⚠️ **Confirm Delete**\n\nReply ID `{rid}` ডিলিট করবেন?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    elif data.startswith("do_delete_"):
        rid = int(data.split("_")[2])
        if delete_reply(rid):
            await query.edit_message_text(
                f"✅ **Reply ID `{rid}` deleted!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text(
                f"❌ Reply ID `{rid}` not found!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
            )

    # ===== SETTINGS =====
    elif data == "menu_settings":
        await show_settings_menu(update, context)

    elif data == "toggle_welcome":
        current = get_setting('welcome_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('welcome_enabled', new)
        await show_settings_menu(update, context)

    elif data == "set_welcome_text":
        await query.edit_message_text(
            "✏️ **Set Welcome Message**\n\nআপনার ওয়েলকাম টেক্সট লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'welcome_text'

    elif data == "set_welcome_photo":
        await query.edit_message_text(
            "🖼 **Set Welcome Photo**\n\nএকটা ফটো পাঠান, সেটা ওয়েলকাম ফটো হবে।\n\nঅথবা Cancel এ ক্লিক করুন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="menu_settings")]])
        )
        context.user_data['awaiting'] = 'welcome_photo'

    elif data == "remove_welcome_photo":
        set_setting('welcome_photo', '')
        await show_settings_menu(update, context)

    elif data == "toggle_blockphoto":
        current = get_setting('block_photo_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('block_photo_enabled', new)
        await show_settings_menu(update, context)

    # ✅ Anti-Spam toggle সরিয়ে দেওয়া হয়েছে

    elif data == "toggle_typing":
        current = get_setting('typing_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('typing_enabled', new)
        await show_settings_menu(update, context)

    # ✅ Typing Time (সেকেন্ডে - কাস্টমাইজেবল)
    elif data == "set_typing_time":
        current = int(get_setting('typing_duration', '5'))
        await query.edit_message_text(
            f"⏱️ **Set Typing Duration**\n\n"
            f"বর্তমান: {current} সেকেন্ড\n\n"
            f"নতুন সময় সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("5s", callback_data="typetime_5"),
                 InlineKeyboardButton("10s", callback_data="typetime_10")],
                [InlineKeyboardButton("15s", callback_data="typetime_15"),
                 InlineKeyboardButton("20s", callback_data="typetime_20")],
                [InlineKeyboardButton("30s", callback_data="typetime_30"),
                 InlineKeyboardButton("60s (1m)", callback_data="typetime_60")],
                [InlineKeyboardButton("120s (2m)", callback_data="typetime_120"),
                 InlineKeyboardButton("180s (3m)", callback_data="typetime_180")],
                [InlineKeyboardButton("300s (5m)", callback_data="typetime_300")],
                [InlineKeyboardButton("🎯 Custom Value", callback_data="typetime_custom")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]),
            parse_mode='Markdown'
        )

    elif data.startswith("typetime_"):
        sec = int(data.split("_")[1])
        set_setting('typing_duration', str(sec))
        await show_settings_menu(update, context)

    # ✅ Custom typing time
    elif data == "typetime_custom":
        await query.edit_message_text(
            "⏱️ **Custom Typing Duration**\n\n"
            "সেকেন্ডে একটি সংখ্যা লিখুন (যেমন: 7, 12, 25):\n\n"
            "বাতিল করতে `/cancel` টাইপ করুন",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'custom_typing_time'

    # ===== ডিফল্ট রিপ্লাই =====
    elif data == "toggle_default_reply":
        current = get_setting('default_reply_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('default_reply_enabled', new)
        await show_settings_menu(update, context)

    elif data == "set_default_reply_text":
        current_default = get_setting('default_reply_text', 
            '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি। দয়া করে সঠিকভাবে লিখুন।')
        await query.edit_message_text(
            f"✏️ **Set Default Reply**\n\n"
            f"বর্তমান ডিফল্ট রিপ্লাই:\n`{current_default}`\n\n"
            f"**নতুন ডিফল্ট রিপ্লাই টেক্সট লিখুন:**\n\n"
            f"(এটা তখনই যাবে যখন কোন keyword match পাবে না)\n\n"
            f"⚠️ *Welcome ON থাকলে Welcome যাবে, Welcome OFF থাকলেই Default Reply যাবে*",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'default_reply_text'

    # ===== STATUS =====
    elif data == "menu_status":
        welcome = '✅ ON' if get_setting('welcome_enabled') == '1' else '❌ OFF'
        blockphoto = '✅ ON' if get_setting('block_photo_enabled') == '1' else '❌ OFF'
        typing = '✅ ON' if get_setting('typing_enabled') == '1' else '❌ OFF'
        typing_time = int(get_setting('typing_duration', '5'))
        default_reply = '✅ ON' if get_setting('default_reply_enabled') == '1' else '❌ OFF'
        
        default_reply_text = get_setting('default_reply_text', 
            '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি।')

        account_line = ""
        if user_account_info:
            account_line = f"👤 Account: {user_account_info.first_name} (@{user_account_info.username or 'N/A'})\n"

        await query.edit_message_text(
            f"📊 **Bot Status**\n\n"
            f"🤖 UserBot: {'✅ Running' if user_bot_running else '❌ Stopped'}\n"
            f"{account_line}"
            f"📝 Total Replies: {get_reply_count()}\n\n"
            f"**Settings:**\n"
            f"👋 Welcome: {welcome}\n"
            f"📸 Block Photo: {blockphoto}\n"
            f"⌨️ Typing: {typing}\n"
            f"⏱️ Duration: {typing_time} sec\n"
            f"💬 Default Reply: {default_reply}\n"
            f"📄 Default Text: {default_reply_text[:40]}...\n\n"
            f"✅ **Seen (✔✔ ডাবল টিক): সবসময় Active**\n"
            f"✅ **Anti-Spam: সরিয়ে দেওয়া হয়েছে**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )


# ===== Settings Menu =====
async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_status = '✅ ON' if get_setting('welcome_enabled') == '1' else '❌ OFF'
    blockphoto_status = '✅ ON' if get_setting('block_photo_enabled') == '1' else '❌ OFF'
    typing_status = '✅ ON' if get_setting('typing_enabled') == '1' else '❌ OFF'
    typing_time = int(get_setting('typing_duration', '5'))
    welcome_photo = '✅ Set' if get_setting('welcome_photo', '') else '❌ None'
    default_reply_status = '✅ ON' if get_setting('default_reply_enabled') == '1' else '❌ OFF'

    keyboard = [
        [InlineKeyboardButton(f"👋 Welcome: {welcome_status}", callback_data="toggle_welcome")],
        [InlineKeyboardButton("✏️ Set Welcome Text", callback_data="set_welcome_text")],
        [InlineKeyboardButton(f"🖼 Welcome Photo: {welcome_photo}", callback_data="set_welcome_photo")],
        [InlineKeyboardButton("❌ Remove Welcome Photo", callback_data="remove_welcome_photo")],
        [InlineKeyboardButton(f"📸 Block Photo: {blockphoto_status}", callback_data="toggle_blockphoto")],
        [InlineKeyboardButton(f"⌨️ Typing: {typing_status}", callback_data="toggle_typing")],
        [InlineKeyboardButton(f"⏱️ Typing Time: {typing_time}s", callback_data="set_typing_time")],
        [InlineKeyboardButton(f"💬 Default Reply: {default_reply_status}", callback_data="toggle_default_reply")],
        [InlineKeyboardButton("✏️ Set Default Reply Text", callback_data="set_default_reply_text")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]

    msg = ("⚙️ **Settings**\n\n"
           "কনফিগার করতে ক্লিক করুন 👇\n\n"
           "✅ **Anti-Spam: সরিয়ে দেওয়া হয়েছে**\n"
           "✅ **Seen (ডাবল টিক): সবসময় Active**")

    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


# ===== Text Message Handler =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    awaiting = context.user_data.get('awaiting', '')
    text = update.message.text.strip()

    # ===== ✅ LOGIN FLOW =====
    if awaiting == 'login_api_id':
        try:
            api_id = int(text)
            context.user_data['login_api_id'] = api_id
            context.user_data['awaiting'] = 'login_api_hash'
            await update.message.reply_text(
                "🔐 **Login - Step 2/3**\n\n"
                f"API ID: `{api_id}` ✅\n\n"
                "এখন আপনার **API Hash** লিখুন:",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid API ID! শুধু সংখ্যা দিন।")
        return

    elif awaiting == 'login_api_hash':
        api_hash = text
        if len(api_hash) < 10:
            await update.message.reply_text("❌ API Hash খুব ছোট! সঠিক Hash দিন।")
            return
        context.user_data['login_api_hash'] = api_hash
        context.user_data['awaiting'] = 'login_session'
        await update.message.reply_text(
            "🔐 **Login - Step 3/3**\n\n"
            f"API ID: `{context.user_data['login_api_id']}` ✅\n"
            f"API Hash: `{api_hash[:8]}...` ✅\n\n"
            "এখন আপনার **String Session** লিখুন:",
            parse_mode='Markdown'
        )
        return

    elif awaiting == 'login_session':
        api_id = context.user_data['login_api_id']
        api_hash = context.user_data['login_api_hash']
        session_str = text

        if len(session_str) < 20:
            await update.message.reply_text("❌ Session string খুব ছোট! সঠিক session দিন।")
            return

        await update.message.reply_text(
            "🔄 Logging in with new account... দয়া করে অপেক্ষা করুন...\n(আপনার config.py তে ম্যানুয়ালি session আপডেট করুন)",
            parse_mode='Markdown'
        )

        context.user_data['awaiting'] = ''
        
        # ✅ config এ session আপডেট করা গেলে restart প্রয়োজন
        await update.message.reply_text(
            "✅ **New account credentials received!**\n\n"
            "⚠️ **গুরুত্বপূর্ণ:** Render এ গিয়ে Environment Variables আপডেট করুন:\n"
            "1. `USER_API_ID` → নতুন API ID\n"
            "2. `USER_API_HASH` → নতুন API Hash\n"
            "3. `USER_STRING_SESSION` → নতুন Session\n\n"
            "তারপর **Deploy** দিন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        return

    # ===== ✅ CUSTOM TYPING TIME =====
    elif awaiting == 'custom_typing_time':
        try:
            sec = int(text)
            if sec < 1 or sec > 600:
                await update.message.reply_text("❌ 1 থেকে 600 সেকেন্ডের মধ্যে মান দিন।")
                return
            set_setting('typing_duration', str(sec))
            context.user_data['awaiting'] = ''
            await update.message.reply_text(
                f"✅ **Typing time set to {sec} seconds!**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]]),
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ শুধু সংখ্যা দিন (যেমন: 7, 12, 30)")
        return

    # NORMAL FLOW
    if awaiting == 'keyword':
        keyword = text
        if not keyword:
            await update.message.reply_text("❌ Keyword empty!")
            return

        context.user_data['add_keyword'] = keyword
        context.user_data['awaiting'] = 'reply_type'

        keyboard = [
            [InlineKeyboardButton("🔑 Exact Match", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]
        ]
        await update.message.reply_text(
            f"➕ **Add Reply - Step 2/3**\n\n🔑 Keyword: `{keyword}`\n\n**রিপ্লাই টাইপ সিলেক্ট করুন:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    elif awaiting == 'reply_text':
        reply_text = text
        if not reply_text:
            await update.message.reply_text("❌ Reply text empty!")
            return

        keyword = context.user_data.get('add_keyword', '')
        rtype = context.user_data.get('reply_type', 'exact')

        reply_id = add_reply(keyword, reply_text, rtype)
        context.user_data['awaiting'] = ''

        type_emoji = "🔑 Exact" if rtype == "exact" else "🔍 Contains"

        await update.message.reply_text(
            f"✅ **Reply Added!**\n\n"
            f"🆔 ID: `{reply_id}`\n"
            f"🔑 Keyword: `{keyword}`\n"
            f"🏷️ Type: {type_emoji}\n"
            f"📄 Reply: {reply_text[:50]}{'...' if len(reply_text) > 50 else ''}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )

    elif awaiting == 'welcome_text':
        text = text
        if not text:
            await update.message.reply_text("❌ Text empty!")
            return
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            f"✅ **Welcome message set!**\n\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )

    elif awaiting == 'default_reply_text':
        text = text
        if not text:
            await update.message.reply_text("❌ Text empty!")
            return
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            f"✅ **Default reply text set!**\n\n{text}",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )


# ===== Photo Handler =====
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    awaiting = context.user_data.get('awaiting', '')

    if awaiting == 'welcome_photo':
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive("welcome_photo.jpg")
        set_setting('welcome_photo', "welcome_photo.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            "✅ **Welcome photo set!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )


# ===== Cancel Command =====
async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data['awaiting'] = ''
    await update.message.reply_text(
        "✅ **Cancelled!**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]])
    )


# ===== Error Handler =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


# ===== Main Function =====
async def run_bot():
    init_db()
    logger.info("✅ Database ready")

    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start, filters=filters.User(ADMIN_ID)))
    app.add_handler(CommandHandler("cancel", cancel_command, filters=filters.User(ADMIN_ID)))

    # Callbacks (button clicks)
    app.add_handler(CallbackQueryHandler(button_callback))

    # Text messages
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), text_handler))

    # Photos
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_ID), photo_handler))

    app.add_error_handler(error_handler)

    await app.initialize()
    await app.start()
    logger.info("✅ Bot started!")

    # Start user account
    asyncio.create_task(start_user_client())

    await app.updater.start_polling()
    await asyncio.Event().wait()


def run_flask():
    """Flask চালানো (Render এর জন্য)"""
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, use_reloader=False)


def run_main():
    """Main function"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())


# ===== Entry Point =====
if __name__ == "__main__":
    # Flask thread
    t = Thread(target=run_flask, daemon=True)
    t.start()
    # Main bot
    run_main()
