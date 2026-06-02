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
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telethon.tl.functions.messages import ReadHistoryRequest
from telethon.errors import FloodWaitError, PeerIdInvalidError

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count
from config import BOT_TOKEN, ADMIN_ID, USER_API_ID, USER_API_HASH, USER_STRING_SESSION

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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

# Track which chats have already received welcome in this session
_welcomed_chats = set()

async def start_user_client():
    global user_client, user_bot_running, user_account_info
    try:
        logger.info("🔄 Starting user client...")
        user_client = TelegramClient(StringSession(USER_STRING_SESSION), USER_API_ID, USER_API_HASH)
        await user_client.start()
        me = await user_client.get_me()
        user_account_info = me
        user_bot_running = True
        logger.info(f"✅ User Account: {me.first_name} (ID: {me.id})")

        from telethon import events

        @user_client.on(events.NewMessage(incoming=True))
        async def auto_reply_handler(event):
            if not event.is_private:
                return

            sender = await event.get_sender()
            sender_id = sender.id

            if sender_id == ADMIN_ID:
                return

            chat_id = event.chat_id
            msg_id = event.message.id

            # ---- SEEN (double tick) ফিক্সড ----
            try:
                await user_client(ReadHistoryRequest(
                    peer=await event.get_input_chat(),
                    max_id=msg_id
                ))
                logger.debug(f"✅ Marked read for {sender_id}")
            except FloodWaitError as e:
                logger.warning(f"Flood wait {e.seconds}s on read")
                await asyncio.sleep(e.seconds + 1)
            except PeerIdInvalidError:
                logger.warning(f"PeerIdInvalid for {sender_id}")
            except Exception as e:
                logger.debug(f"Read mark minor: {e}")

            # ---- Block photo ----
            if event.message.media:
                is_photo = isinstance(event.message.media, MessageMediaPhoto)
                is_sticker = hasattr(event.message.media, 'document') and hasattr(event.message.media.document, 'mime_type') and 'sticker' in (event.message.media.document.mime_type or '')
                
                if is_photo:
                    if get_setting('block_photo_enabled', '1') == '1':
                        try:
                            await user_client(BlockRequest(id=sender_id))
                            logger.info(f"🚫 Blocked {sender_id} for photo")
                        except:
                            pass
                        return

            typing_enabled = get_setting('typing_enabled', '1') == '1'
            typing_duration = int(get_setting('typing_duration', '5'))

            msg_text = event.message.text or ""
            msg_lower = msg_text.lower().strip()

            replies = get_all_replies()
            matched = False

            welcome_photo = get_setting('welcome_photo', '')
            default_photo = get_setting('default_photo', '')

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

            if not matched:
                # ---- যদি chat টা new হয়, তাহলে welcome পাঠাই (একবার) ----
                if chat_id not in _welcomed_chats:
                    welcome_enabled = get_setting('welcome_enabled', '1') == '1'
                    if welcome_enabled:
                        _welcomed_chats.add(chat_id)
                        if typing_enabled:
                            async with user_client.action(event.chat_id, "typing"):
                                await asyncio.sleep(typing_duration)
                        welcome_msg = get_setting('welcome_message', '👋 Welcome!')
                        
                        if welcome_photo and os.path.exists(welcome_photo):
                            try:
                                await user_client.send_file(event.chat_id, welcome_photo, caption=welcome_msg)
                            except:
                                await event.respond(welcome_msg)
                        else:
                            await event.respond(welcome_msg)
                    else:
                        # welcome বন্ধ থাকলে সরাসরি default reply
                        _welcomed_chats.add(chat_id)
                        await _send_default_reply(event, user_client, typing_enabled, typing_duration, default_photo)
                else:
                    # ---- একবার welcome হয়ে গেছে, এখন default reply পাঠাই ----
                    await _send_default_reply(event, user_client, typing_enabled, typing_duration, default_photo)

        logger.info("✅ User client started, keeping alive...")
        while True:
            try:
                await asyncio.sleep(30)
                me = await user_client.get_me()
                if me:
                    logger.debug(f"Ping: {me.first_name}")
            except Exception as e:
                logger.warning(f"Ping failed: {e}")
                user_bot_running = False
                break

    except Exception as e:
        logger.error(f"❌ User account error: {e}")
        user_bot_running = False


async def _send_default_reply(event, client, typing_enabled, typing_duration, default_photo):
    """Default reply পাঠায়, সাথে ফটো থাকলে ফটো সহ"""
    default_reply_enabled = get_setting('default_reply_enabled', '1') == '1'
    if default_reply_enabled:
        if typing_enabled:
            async with client.action(event.chat_id, "typing"):
                await asyncio.sleep(typing_duration)
        default_reply = get_setting('default_reply_text',
            '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি।')
        
        if default_photo and os.path.exists(default_photo):
            try:
                await client.send_file(event.chat_id, default_photo, caption=default_reply)
            except:
                await event.respond(default_reply)
        else:
            await event.respond(default_reply)


# ==============================================
#    BOT COMMANDS & BUTTONS
# ==============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    await show_main_menu(update, context)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_info = ""
    if user_account_info:
        user_info = f"👤 {user_account_info.first_name} (ID: {user_account_info.id})"
    
    keyboard = [
        [InlineKeyboardButton("📋 Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("➕ Add Reply", callback_data="menu_add_reply")],
        [InlineKeyboardButton("🗑 Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
        [InlineKeyboardButton("🔐 Login New Account", callback_data="menu_login")]
    ]
    text = (
        "🤖 **UserBot Panel**\n\n"
        f"🟢 UserBot: {'✅ Running' if user_bot_running else '❌ Stopped'}\n"
        f"📝 Replies: {get_reply_count()}\n"
        f"{user_info}\n\n"
        "বাটন ক্লিক করুন 👇"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await show_main_menu(update, context)

    elif data == "menu_login":
        await query.edit_message_text(
            "🔐 **Login - Step 1/3**\n\nAPI ID লিখুন (শুধু সংখ্যা):\n`/cancel` বাতিল",
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'login_api_id'

    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 No replies! ➕ Add Reply দিয়ে যোগ করুন।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])
            )
            return
        page = int(context.user_data.get('reply_page', 0))
        per_page = 5
        total = (len(replies) + per_page - 1) // per_page
        start = page * per_page
        end = start + per_page
        page_list = replies[start:end]
        msg = f"📋 **Replies (Page {page+1}/{total})**\n\n"
        for r in page_list:
            rid, kw, rt, tp = r
            e = "🔑" if tp == "exact" else "🔍"
            msg += f"{e} ID:{rid} | `{kw[:20]}`\n  ➜ {rt[:40]}...\n\n"
        kb = []
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"rp_{page-1}"))
        if page < total - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"rp_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("rp_"):
        context.user_data['reply_page'] = int(data.split("_")[1])
        await button_callback(update, context)

    elif data == "menu_add_reply":
        await query.edit_message_text(
            "➕ **Step 1/3**\n\nকীওয়ার্ড লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'keyword'

    elif data == "reply_type_exact":
        context.user_data['reply_type'] = 'exact'
        await query.edit_message_text(
            f"➕ **Step 3/3**\n\nKeyword: `{context.user_data.get('add_keyword','')}`\nType: Exact\n\nরিপ্লাই টেক্সট লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'reply_text'

    elif data == "reply_type_contains":
        context.user_data['reply_type'] = 'contains'
        await query.edit_message_text(
            f"➕ **Step 3/3**\n\nKeyword: `{context.user_data.get('add_keyword','')}`\nType: Contains\n\nরিপ্লাই টেক্সট লিখুন:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
        context.user_data['awaiting'] = 'reply_text'

    elif data == "menu_del_reply":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text("📭 No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
            return
        kb = []
        for r in replies[:10]:
            rid, kw, _, tp = r
            e = "🔑" if tp == "exact" else "🔍"
            kb.append([InlineKeyboardButton(f"{e} ID:{rid} {kw[:20]}", callback_data=f"cd_{rid}")])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await query.edit_message_text("🗑 **Delete Reply**\n\nযেটা ডিলিট করবেন সেটিতে ক্লিক করুন:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("cd_"):
        rid = int(data.split("_")[1])
        kb = [
            [InlineKeyboardButton("✅ হ্যাঁ", callback_data=f"dd_{rid}")],
            [InlineKeyboardButton("❌ না", callback_data="menu_del_reply")]
        ]
        await query.edit_message_text(f"⚠️ Reply ID `{rid}` ডিলিট করবেন?", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data.startswith("dd_"):
        rid = int(data.split("_")[1])
        if delete_reply(rid):
            await query.edit_message_text(f"✅ Deleted ID {rid}!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
        else:
            await query.edit_message_text("❌ Not found!")

    elif data == "menu_settings":
        w = '✅ ON' if get_setting('welcome_enabled','1')=='1' else '❌ OFF'
        bp = '✅ ON' if get_setting('block_photo_enabled','1')=='1' else '❌ OFF'
        t = '✅ ON' if get_setting('typing_enabled','1')=='1' else '❌ OFF'
        tt = int(get_setting('typing_duration','5'))
        dr = '✅ ON' if get_setting('default_reply_enabled','1')=='1' else '❌ OFF'
        kb = [
            [InlineKeyboardButton(f"👋 Welcome {w}", callback_data="tw")],
            [InlineKeyboardButton("✏️ Welcome Text", callback_data="swt")],
            [InlineKeyboardButton("🖼️ Welcome Photo", callback_data="swp")],
            [InlineKeyboardButton(f"📸 Block Photo {bp}", callback_data="tbp")],
            [InlineKeyboardButton(f"⌨️ Typing {t}", callback_data="tty")],
            [InlineKeyboardButton(f"⏱️ Typing {tt}s", callback_data="stt")],
            [InlineKeyboardButton(f"💬 Default Reply {dr}", callback_data="tdr")],
            [InlineKeyboardButton("✏️ Default Text", callback_data="sdrt")],
            [InlineKeyboardButton("🖼️ Default Photo", callback_data="sdp")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "⚙️ **Settings**\n\nSelect an option below:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif data == "tw":
        cur = get_setting('welcome_enabled','1')
        set_setting('welcome_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "swt":
        await query.edit_message_text("✏️ Welcome message লিখুন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'welcome_text'

    elif data == "swp":
        await query.edit_message_text("🖼️ Welcome photo এর file path দিন (যেমন: /home/user/welcome.jpg)\n\nঅথবা photo টি Send করুন।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'welcome_photo'

    elif data == "sdp":
        await query.edit_message_text("🖼️ Default reply photo এর file path দিন:\n\nঅথবা photo টি Send করুন।", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'default_photo'

    elif data == "tbp":
        cur = get_setting('block_photo_enabled','1')
        set_setting('block_photo_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "tty":
        cur = get_setting('typing_enabled','1')
        set_setting('typing_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "stt":
        current = int(get_setting('typing_duration','5'))
        await query.edit_message_text(
            f"⏱️ Current: {current}s\n\nSelect:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("5s", callback_data="tt_5"), InlineKeyboardButton("10s", callback_data="tt_10")],
                [InlineKeyboardButton("15s", callback_data="tt_15"), InlineKeyboardButton("30s", callback_data="tt_30")],
                [InlineKeyboardButton("60s", callback_data="tt_60"), InlineKeyboardButton("🎯 Custom", callback_data="tt_c")],
                [InlineKeyboardButton("🔙", callback_data="menu_settings")]
            ]), parse_mode='Markdown')

    elif data.startswith("tt_") and data != "tt_c":
        sec = int(data.split("_")[1])
        set_setting('typing_duration', str(sec))
        await button_callback(update, context)

    elif data == "tt_c":
        await query.edit_message_text("⏱️ সেকেন্ড লিখুন (যেমন: 7):", parse_mode='Markdown')
        context.user_data['awaiting'] = 'custom_typing_time'

    elif data == "tdr":
        cur = get_setting('default_reply_enabled','1')
        set_setting('default_reply_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "sdrt":
        await query.edit_message_text("✏️ Default reply text লিখুন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'default_reply_text'

    elif data == "menu_status":
        w = '✅ ON' if get_setting('welcome_enabled','1')=='1' else '❌ OFF'
        bp = '✅ ON' if get_setting('block_photo_enabled','1')=='1' else '❌ OFF'
        t = '✅ ON' if get_setting('typing_enabled','1')=='1' else '❌ OFF'
        tt = int(get_setting('typing_duration','5'))
        dr = '✅ ON' if get_setting('default_reply_enabled','1')=='1' else '❌ OFF'
        ac = ""
        if user_account_info:
            ac = f"👤 {user_account_info.first_name}\n"
        await query.edit_message_text(
            f"📊 **Status**\n\n🤖 UserBot: {'✅ Running' if user_bot_running else '❌ Stopped'}\n{ac}📝 Replies: {get_reply_count()}\n\n"
            f"👋 Welcome: {w}\n📸 Block Photo: {bp}\n⌨️ Typing: {t} ({tt}s)\n💬 Default: {dr}\n\n✅ Seen ✔✔: Always Active",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]), parse_mode='Markdown')


# ===== Text Handler =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    text = update.message.text.strip()
    awaiting = context.user_data.get('awaiting', '')

    if awaiting == 'login_api_id':
        try:
            context.user_data['login_api_id'] = int(text)
            context.user_data['awaiting'] = 'login_api_hash'
            await update.message.reply_text(f"🔐 Step 2/3\nAPI ID: `{text}`\n\nAPI Hash লিখুন:", parse_mode='Markdown')
        except:
            await update.message.reply_text("❌ শুধু সংখ্যা!")
        return

    elif awaiting == 'login_api_hash':
        context.user_data['login_api_hash'] = text
        context.user_data['awaiting'] = 'login_session'
        await update.message.reply_text("🔐 Step 3/3\n\nString Session লিখুন:", parse_mode='Markdown')
        return

    elif awaiting == 'login_session':
        await update.message.reply_text(
            "✅ Received!\n\n⚠️ Render এ গিয়ে Environment Variables আপডেট করুন:\n`USER_API_ID`, `USER_API_HASH`, `USER_STRING_SESSION`\n\nতারপর Deploy দিন।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menu", callback_data="main_menu")]]))
        context.user_data['awaiting'] = ''
        return

    elif awaiting == 'custom_typing_time':
        try:
            s = int(text)
            if 1 <= s <= 600:
                set_setting('typing_duration', str(s))
                context.user_data['awaiting'] = ''
                await update.message.reply_text(f"✅ Typing time: {s}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
            else:
                await update.message.reply_text("❌ 1-600 এর মধ্যে দিন।")
        except:
            await update.message.reply_text("❌ শুধু সংখ্যা!")
        return

    elif awaiting == 'welcome_photo':
        set_setting('welcome_photo', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Welcome photo path set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        return

    elif awaiting == 'default_photo':
        set_setting('default_photo', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Default reply photo path set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        return

    if awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        kb = [
            [InlineKeyboardButton("🔑 Exact", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
        ]
        await update.message.reply_text(f"🔑 Keyword: `{text}`\n\nটাইপ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')

    elif awaiting == 'reply_text':
        kw = context.user_data.get('add_keyword','')
        tp = context.user_data.get('reply_type','exact')
        rid = add_reply(kw, text, tp)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ Added! (ID: {rid})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))

    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ Welcome text set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))

    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ Default reply set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data['awaiting'] = ''
    await update.message.reply_text("✅ Cancelled!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


# ===== Photo handler via Telegram Bot =====
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """যখন Admin photo পাঠায়, সেটা ডাউনলোড করে path সেভ করে"""
    if update.effective_user.id != ADMIN_ID:
        return
    awaiting = context.user_data.get('awaiting', '')
    if awaiting in ('welcome_photo', 'default_photo'):
        photo = update.message.photo[-1]  # highest res
        file = await photo.get_file()
        # Download to a local path
        os.makedirs('photos', exist_ok=True)
        ext = 'jpg'
        fname = f"photos/{awaiting}_{photo.file_id[:20]}.{ext}"
        await file.download_to_drive(fname)
        if awaiting == 'welcome_photo':
            set_setting('welcome_photo', fname)
            await update.message.reply_text(f"✅ Welcome photo saved!\nPath: `{fname}`", parse_mode='Markdown')
        else:
            set_setting('default_photo', fname)
            await update.message.reply_text(f"✅ Default photo saved!\nPath: `{fname}`", parse_mode='Markdown')
        context.user_data['awaiting'] = ''
        context.user_data.pop('awaiting', None)
    else:
        # Plain photo with no awaiting state — ignore or could save as reply photo
        pass


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

    # User account start
    asyncio.create_task(start_user_client())

    # Polling start
    await app.updater.start_polling()

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

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
