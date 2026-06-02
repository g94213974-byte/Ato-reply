import asyncio
import os
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

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
user_account_info = None

async def start_user_client():
    global user_client, user_bot_running, user_account_info
    try:
        logger.info("🔄 Connecting to Telegram user account...")
        user_client = TelegramClient(StringSession(USER_STRING_SESSION), USER_API_ID, USER_API_HASH)
        await user_client.start()
        me = await user_client.get_me()
        user_account_info = me
        logger.info(f"✅ User Account: {me.first_name} (ID: {me.id})")
        user_bot_running = True

        from telethon import events

        @user_client.on(events.NewMessage(incoming=True))
        async def auto_reply_handler(event):
            if not event.is_private:
                return

            sender = await event.get_sender()
            sender_id = sender.id
            
            logger.info(f"📩 Message from {sender_id}: {event.message.text[:50] if event.message.text else '[no text]'}")

            if sender_id == ADMIN_ID:
                logger.info("⏭️ Admin message - skipping")
                return

            # ✅ SEEN (ডাবল টিক)
            try:
                await user_client.send_read_acknowledge(event.message)
                logger.info(f"✅ Marked as read for {sender_id}")
            except Exception as e:
                logger.warning(f"⚠️ Mark read error: {e}")

            # Block photo
            if event.message.media and isinstance(event.message.media, MessageMediaPhoto):
                if get_setting('block_photo_enabled', '1') == '1':
                    try:
                        await user_client(BlockRequest(id=sender_id))
                        logger.info(f"🚫 Blocked {sender_id} for photo")
                    except:
                        pass
                    return

            # Typing
            typing_enabled = get_setting('typing_enabled', '1') == '1'
            typing_duration = int(get_setting('typing_duration', '5'))

            msg_text = event.message.text or ""
            msg_lower = msg_text.lower().strip()

            # CHECK REPLIES
            replies = get_all_replies()
            matched = False
            
            logger.info(f"🔍 Checking {len(replies)} replies for keyword match...")

            for rid, keyword, reply_text, rtype in replies:
                kw = keyword.lower().strip()
                if rtype == "exact" and msg_lower == kw:
                    matched = True
                    logger.info(f"✅ Exact match found: {keyword}")
                    if typing_enabled:
                        async with user_client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    await event.respond(reply_text)
                    logger.info(f"✅ Reply sent (exact): {reply_text[:30]}...")
                    break
                elif rtype == "contains" and kw in msg_lower:
                    matched = True
                    logger.info(f"✅ Contains match found: {keyword}")
                    if typing_enabled:
                        async with user_client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    await event.respond(reply_text)
                    logger.info(f"✅ Reply sent (contains): {reply_text[:30]}...")
                    break

            # NO MATCH
            if not matched:
                logger.info("❌ No keyword match found")
                welcome_enabled = get_setting('welcome_enabled', '1') == '1'
                
                if welcome_enabled:
                    logger.info("👋 Sending welcome message...")
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
                    logger.info(f"✅ Welcome sent: {welcome_msg[:30]}...")
                
                else:
                    default_reply_enabled = get_setting('default_reply_enabled', '1') == '1'
                    if default_reply_enabled:
                        logger.info("💬 Sending default reply...")
                        if typing_enabled:
                            async with user_client.action(event.chat_id, "typing"):
                                await asyncio.sleep(typing_duration)
                        
                        default_reply = get_setting('default_reply_text', 
                            '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি। দয়া করে সঠিকভাবে লিখুন।')
                        await event.respond(default_reply)
                        logger.info(f"✅ Default reply sent: {default_reply[:30]}...")
                    else:
                        logger.info("⏭️ Default reply disabled, no reply sent")

        logger.info("✅ Event handler registered, running until disconnected...")
        await user_client.run_until_disconnected()
        
    except Exception as e:
        logger.error(f"❌ User account error: {e}")
        user_bot_running = False


# ==============================================
#    BOT COMMANDS (Shudu Button)
# ==============================================

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
        [InlineKeyboardButton("🔐 Login New Account", callback_data="menu_login")]
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


# ===== Callback Handler =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await show_main_menu(update, context)

    elif data == "menu_login":
        await query.edit_message_text(
            "🔐 **Login New Account - Step 1/3**\n\n"
            "আপনার **API ID** লিখুন (শুধু সংখ্যা):\n\n"
            "বাতিল করতে `/cancel` টাইপ করুন",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'login_api_id'

    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 **No replies yet!**\n\n➕ Add Reply বাটনে ক্লিক করুন।",
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
            )
        else:
            await query.edit_message_text(f"❌ Reply ID `{rid}` not found!")

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
            "🖼 **Set Welcome Photo**\n\nএকটা ফটো পাঠান, সেটা ওয়েলকাম ফটো হবে।",
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

    elif data == "toggle_typing":
        current = get_setting('typing_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('typing_enabled', new)
        await show_settings_menu(update, context)

    elif data == "set_typing_time":
        current = int(get_setting('typing_duration', '5'))
        await query.edit_message_text(
            f"⏱️ **Set Typing Duration**\n\nবর্তমান: {current} সেকেন্ড\n\nনতুন সময় সিলেক্ট করুন:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("5s", callback_data="typetime_5"),
                 InlineKeyboardButton("10s", callback_data="typetime_10")],
                [InlineKeyboardButton("15s", callback_data="typetime_15"),
                 InlineKeyboardButton("20s", callback_data="typetime_20")],
                [InlineKeyboardButton("30s", callback_data="typetime_30"),
                 InlineKeyboardButton("60s (1m)", callback_data="typetime_60")],
                [InlineKeyboardButton("🎯 Custom", callback_data="typetime_custom")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_settings")]
            ]),
            parse_mode='Markdown'
        )

    elif data.startswith("typetime_"):
        sec = int(data.split("_")[1])
        set_setting('typing_duration', str(sec))
        await show_settings_menu(update, context)

    elif data == "typetime_custom":
        await query.edit_message_text(
            "⏱️ **Custom Typing Duration**\n\nসেকেন্ডে সংখ্যা লিখুন (যেমন: 7, 12):\n\nবাতিলে `/cancel`",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'custom_typing_time'

    elif data == "toggle_default_reply":
        current = get_setting('default_reply_enabled', '1')
        new = '0' if current == '1' else '1'
        set_setting('default_reply_enabled', new)
        await show_settings_menu(update, context)

    elif data == "set_default_reply_text":
        await query.edit_message_text(
            "✏️ **Set Default Reply**\n\nনতুন ডিফল্ট রিপ্লাই টেক্সট লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="menu_settings")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'default_reply_text'

    elif data == "menu_status":
        welcome = '✅ ON' if get_setting('welcome_enabled') == '1' else '❌ OFF'
        blockphoto = '✅ ON' if get_setting('block_photo_enabled') == '1' else '❌ OFF'
        typing = '✅ ON' if get_setting('typing_enabled') == '1' else '❌ OFF'
        typing_time = int(get_setting('typing_duration', '5'))
        default_reply = '✅ ON' if get_setting('default_reply_enabled') == '1' else '❌ OFF'

        account_line = ""
        if user_account_info:
            account_line = f"👤 Account: {user_account_info.first_name}\n"

        await query.edit_message_text(
            f"📊 **Bot Status**\n\n"
            f"🤖 UserBot: {'✅ Running' if user_bot_running else '❌ Stopped'}\n"
            f"{account_line}"
            f"📝 Total Replies: {get_reply_count()}\n\n"
            f"👋 Welcome: {welcome}\n"
            f"📸 Block Photo: {blockphoto}\n"
            f"⌨️ Typing: {typing} ({typing_time}s)\n"
            f"💬 Default Reply: {default_reply}\n\n"
            f"✅ **Seen (✔✔): সবসময় Active**\n"
            f"✅ **Anti-Spam: সরিয়ে দেওয়া হয়েছে**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )


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
        [InlineKeyboardButton(f"🖼 Photo: {welcome_photo}", callback_data="set_welcome_photo")],
        [InlineKeyboardButton("❌ Remove Photo", callback_data="remove_welcome_photo")],
        [InlineKeyboardButton(f"📸 Block Photo: {blockphoto_status}", callback_data="toggle_blockphoto")],
        [InlineKeyboardButton(f"⌨️ Typing: {typing_status}", callback_data="toggle_typing")],
        [InlineKeyboardButton(f"⏱️ Typing: {typing_time}s", callback_data="set_typing_time")],
        [InlineKeyboardButton(f"💬 Default Reply: {default_reply_status}", callback_data="toggle_default_reply")],
        [InlineKeyboardButton("✏️ Set Default Text", callback_data="set_default_reply_text")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ]

    await update.callback_query.edit_message_text(
        "⚙️ **Settings**\n\n✅ **Seen (✔✔): Always ON**\n✅ **Anti-Spam: Removed**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )


# ===== Text Handler =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    awaiting = context.user_data.get('awaiting', '')
    text = update.message.text.strip()

    if awaiting == 'login_api_id':
        try:
            api_id = int(text)
            context.user_data['login_api_id'] = api_id
            context.user_data['awaiting'] = 'login_api_hash'
            await update.message.reply_text(
                f"🔐 **Step 2/3**\nAPI ID: `{api_id}` ✅\n\nএখন **API Hash** লিখুন:",
                parse_mode='Markdown'
            )
        except ValueError:
            await update.message.reply_text("❌ শুধু সংখ্যা দিন!")
        return

    elif awaiting == 'login_api_hash':
        context.user_data['login_api_hash'] = text
        context.user_data['awaiting'] = 'login_session'
        await update.message.reply_text(
            "🔐 **Step 3/3**\n\nএখন **String Session** লিখুন:",
            parse_mode='Markdown'
        )
        return

    elif awaiting == 'login_session':
        await update.message.reply_text(
            "✅ **Received!**\n\n⚠️ Render এ Environment Variables আপডেট করুন:\n"
            "`USER_API_ID`, `USER_API_HASH`, `USER_STRING_SESSION`\n\nতারপর Deploy দিন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
        )
        context.user_data['awaiting'] = ''
        return

    elif awaiting == 'custom_typing_time':
        try:
            sec = int(text)
            if sec < 1 or sec > 600:
                await update.message.reply_text("❌ 1-600 সেকেন্ডের মধ্যে দিন।")
                return
            set_setting('typing_duration', str(sec))
            context.user_data['awaiting'] = ''
            await update.message.reply_text(
                f"✅ **Typing time: {sec}s**",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]])
            )
        except ValueError:
            await update.message.reply_text("❌ শুধু সংখ্যা দিন!")
        return

    if awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        keyboard = [
            [InlineKeyboardButton("🔑 Exact Match", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
        ]
        await update.message.reply_text(
            f"🔑 Keyword: `{text}`\n\n**টাইপ সিলেক্ট করুন:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    elif awaiting == 'reply_text':
        keyword = context.user_data.get('add_keyword', '')
        rtype = context.user_data.get('reply_type', 'exact')
        reply_id = add_reply(keyword, text, rtype)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            f"✅ **Reply Added!** (ID: {reply_id})",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
        )

    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            f"✅ **Welcome text set!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]])
        )

    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            f"✅ **Default reply set!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]])
        )


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if context.user_data.get('awaiting') == 'welcome_photo':
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        await file.download_to_drive("welcome_photo.jpg")
        set_setting('welcome_photo', "welcome_photo.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text(
            "✅ **Photo set!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Settings", callback_data="menu_settings")]])
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data['awaiting'] = ''
    await update.message.reply_text(
        "✅ **Cancelled!**",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]])
    )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


async def run_bot():
    init_db()
    logger.info("✅ Database ready")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start, filters=filters.User(ADMIN_ID)))
    app.add_handler(CommandHandler("cancel", cancel_command, filters=filters.User(ADMIN_ID)))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & filters.User(ADMIN_ID), text_handler))
    app.add_handler(MessageHandler(filters.PHOTO & filters.User(ADMIN_ID), photo_handler))
    app.add_error_handler(error_handler)

    await app.initialize()
    await app.start()
    logger.info("✅ Bot started!")

    asyncio.create_task(start_user_client())

    await app.updater.start_polling()
    await asyncio.Event().wait()


def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, use_reloader=False)


def run_main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_bot())


if __name__ == "__main__":
    t = Thread(target=run_flask, daemon=True)
    t.start()
    run_main()
