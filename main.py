import asyncio
import os
import logging
import random
from threading import Thread

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.types import MessageMediaPhoto
from telethon.tl.functions.messages import ReadHistoryRequest
from telethon.errors import FloodWaitError, PeerIdInvalidError

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count
from config import BOT_TOKEN, ADMIN_ID, ACCOUNTS

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "running"})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200


# ==============================================
#    MULTI ACCOUNT MANAGER
# ==============================================
accounts = []        # list of dicts: {id, name, client, enabled, api_id, api_hash, session}
_welcomed_chats = set()
_account_index = 0

async def start_all_accounts():
    """config.py/Environment Variables থেকে সব accounts কানেক্ট করে"""
    if not ACCOUNTS:
        logger.warning("⚠️ No accounts configured in Environment Variables!")
        return
    
    logger.info(f"🔄 Starting {len(ACCOUNTS)} accounts from Environment Variables...")
    
    tasks = []
    for acc_data in ACCOUNTS:
        tasks.append(start_single_account(
            acc_data['session'],
            acc_data['api_id'],
            acc_data['api_hash']
        ))
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    success = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"❌ Account {i+1} failed: {result}")
        elif result:
            success += 1
            accounts.append(result)
    
    logger.info(f"✅ {success}/{len(ACCOUNTS)} accounts connected successfully!")


async def start_single_account(session_string, api_id, api_hash):
    """একটি single account start করে"""
    try:
        client = TelegramClient(StringSession(session_string), api_id, api_hash)
        await client.start()
        me = await client.get_me()
        
        acc_info = {
            'id': me.id,
            'name': me.first_name or f"User{me.id}",
            'client': client,
            'enabled': True,
            'api_id': api_id,
            'api_hash': api_hash,
            'session': session_string
        }
        
        logger.info(f"✅ Connected: {me.first_name} (ID: {me.id})")
        
        # Register auto-reply handler for this client
        _register_handler(client, acc_info)
        
        return acc_info
    except Exception as e:
        logger.error(f"❌ Failed to start account (API_ID: {api_id}): {e}")
        raise


def _register_handler(client, acc_info):
    """প্রতি account এর জন্য auto-reply handler বসায়"""
    from telethon import events
    
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        # Skip non-private chats
        if not event.is_private:
            return
        
        sender = await event.get_sender()
        sender_id = sender.id
        
        # Skip admin
        if sender_id == ADMIN_ID:
            return
        
        # Skip if this account is disabled
        if not acc_info.get('enabled', True):
            return
        
        chat_id = event.chat_id
        msg_id = event.message.id
        
        # --- SEEN (double tick) ---
        try:
            await client(ReadHistoryRequest(
                peer=await event.get_input_chat(),
                max_id=msg_id
            ))
        except FloodWaitError as e:
            await asyncio.sleep(e.seconds + 1)
        except:
            pass
        
        # --- Block Photo ---
        if event.message.media and isinstance(event.message.media, MessageMediaPhoto):
            if get_setting('block_photo_enabled', '1') == '1':
                try:
                    await client(BlockRequest(id=sender_id))
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
        
        # Check keyword replies
        for rid, keyword, reply_text, rtype in replies:
            kw = keyword.lower().strip()
            if rtype == "exact" and msg_lower == kw:
                matched = True
                if typing_enabled:
                    async with client.action(event.chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                await event.respond(reply_text)
                break
            elif rtype == "contains" and kw in msg_lower:
                matched = True
                if typing_enabled:
                    async with client.action(event.chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                await event.respond(reply_text)
                break
        
        # No keyword matched
        if not matched:
            if chat_id not in _welcomed_chats:
                welcome_enabled = get_setting('welcome_enabled', '1') == '1'
                if welcome_enabled:
                    _welcomed_chats.add(chat_id)
                    if typing_enabled:
                        async with client.action(event.chat_id, "typing"):
                            await asyncio.sleep(typing_duration)
                    welcome_msg = get_setting('welcome_message', '👋 Welcome!')
                    if welcome_photo and os.path.exists(welcome_photo):
                        try:
                            await client.send_file(event.chat_id, welcome_photo, caption=welcome_msg)
                        except:
                            await event.respond(welcome_msg)
                    else:
                        await event.respond(welcome_msg)
                else:
                    _welcomed_chats.add(chat_id)
                    await _send_default_reply(event, client, typing_enabled, typing_duration, default_photo)
            else:
                await _send_default_reply(event, client, typing_enabled, typing_duration, default_photo)


async def _send_default_reply(event, client, typing_enabled, typing_duration, default_photo):
    """Default reply পাঠায়"""
    default_reply_enabled = get_setting('default_reply_enabled', '1') == '1'
    if not default_reply_enabled:
        return
    
    if typing_enabled:
        async with client.action(event.chat_id, "typing"):
            await asyncio.sleep(typing_duration)
    
    default_reply = get_setting('default_reply_text', '🤖 আমি এখনো আপনার প্রশ্ন বুঝতে পারিনি।')
    
    if default_photo and os.path.exists(default_photo):
        try:
            await client.send_file(event.chat_id, default_photo, caption=default_reply)
        except:
            await event.respond(default_reply)
    else:
        await event.respond(default_reply)


def get_next_account():
    """Enabled accounts থেকে round-robin এ একটি account সিলেক্ট করে"""
    global _account_index
    enabled = [a for a in accounts if a.get('enabled', True)]
    if not enabled:
        return None
    idx = _account_index % len(enabled)
    _account_index += 1
    return enabled[idx]


# ==============================================
#    BOT COMMANDS
# ==============================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!")
        return
    await show_main_menu(update, context)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    connected = len(accounts)
    enabled_count = len([a for a in accounts if a.get('enabled', True)])
    configured = len(ACCOUNTS)
    
    keyboard = [
        [InlineKeyboardButton("📋 Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("➕ Add Reply", callback_data="menu_add_reply")],
        [InlineKeyboardButton("🗑 Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("👥 Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
    ]
    
    text = (
        "🤖 **Multi-Account UserBot**\n\n"
        f"🟢 Connected: {connected}/{configured}\n"
        f"✅ Active: {enabled_count}\n"
        f"📝 Replies: {get_reply_count()}\n\n"
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
    
    # ===== ACCOUNTS =====
    elif data == "menu_accounts":
        if not accounts:
            await query.edit_message_text(
                "👥 **No Accounts Connected**\n\n"
                "Environment Variables এ API_ID_1, API_HASH_1, SESSION_1 ইত্যাদি সেট করুন।\n\n"
                "10 পর্যন্ত account যোগ করতে পারবেন।",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]]),
                parse_mode='Markdown'
            )
            return
        
        msg = "👥 **Connected Accounts**\n\n"
        kb = []
        for i, acc in enumerate(accounts):
            status = "🟢" if acc.get('enabled', True) else "🔴"
            acct_num = i + 1
            msg += f"{status} **{acct_num}.** {acc['name']} (ID: {acc['id']})\n"
            kb.append([
                InlineKeyboardButton(
                    f"{'🔴 Disable' if acc.get('enabled',True) else '🟢 Enable'} #{acct_num}",
                    callback_data=f"tog_{i}"
                )
            ])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith("tog_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            accounts[idx]['enabled'] = not accounts[idx].get('enabled', True)
            status = "Enabled" if accounts[idx]['enabled'] else "Disabled"
            await query.answer(f"{status}: {accounts[idx]['name']}")
        await button_callback(update, context)
    
    # ===== REPLIES =====
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
    
    # ===== SETTINGS =====
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
            "⚙️ **Settings**\n\nSelect an option:",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "tw":
        cur = get_setting('welcome_enabled','1')
        set_setting('welcome_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    
    elif data == "swt":
        await query.edit_message_text("✏️ Welcome message লিখুন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'welcome_text'
    
    elif data == "swp":
        await query.edit_message_text("🖼️ Welcome photo পাঠান অথবা file path দিন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        context.user_data['awaiting'] = 'welcome_photo'
    
    elif data == "sdp":
        await query.edit_message_text("🖼️ Default reply photo পাঠান অথবা file path দিন:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
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
        
        accs_status = ""
        for i, acc in enumerate(accounts):
            s = "🟢" if acc.get('enabled',True) else "🔴"
            accs_status += f"{s} #{i+1} {acc['name']}\n"
        
        await query.edit_message_text(
            f"📊 **Status**\n\n"
            f"👥 Accounts: {len([a for a in accounts if a.get('enabled',True)])}/{len(accounts)} active\n\n"
            f"**Accounts:**\n{accs_status}\n"
            f"📝 Replies: {get_reply_count()}\n\n"
            f"👋 Welcome: {w}\n📸 Block Photo: {bp}\n⌨️ Typing: {t} ({tt}s)\n💬 Default: {dr}\n\n✅ Seen ✔✔: Always Active",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]), parse_mode='Markdown')


# ===== TEXT HANDLER =====
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    text = update.message.text.strip()
    awaiting = context.user_data.get('awaiting', '')
    
    if awaiting == 'custom_typing_time':
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
    
    elif awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        kb = [
            [InlineKeyboardButton("🔑 Exact", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
        ]
        await update.message.reply_text(f"🔑 Keyword: `{text}`\n\nটাইপ সিলেক্ট করুন:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return
    
    elif awaiting == 'reply_text':
        kw = context.user_data.get('add_keyword', '')
        tp = context.user_data.get('reply_type', 'exact')
        rid = add_reply(kw, text, tp)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ Added! (ID: {rid})", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
        return
    
    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Welcome text set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
        return
    
    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Default reply set!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    context.user_data['awaiting'] = ''
    await update.message.reply_text("✅ Cancelled!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin photo পাঠালে সেটা download করে save করে"""
    if update.effective_user.id != ADMIN_ID:
        return
    awaiting = context.user_data.get('awaiting', '')
    if awaiting in ('welcome_photo', 'default_photo'):
        photo = update.message.photo[-1]
        file = await photo.get_file()
        os.makedirs('photos', exist_ok=True)
        fname = f"photos/{awaiting}_{photo.file_id[:20]}.jpg"
        await file.download_to_drive(fname)
        if awaiting == 'welcome_photo':
            set_setting('welcome_photo', fname)
            await update.message.reply_text(f"✅ Welcome photo saved!\n`{fname}`", parse_mode='Markdown')
        else:
            set_setting('default_photo', fname)
            await update.message.reply_text(f"✅ Default photo saved!\n`{fname}`", parse_mode='Markdown')
        context.user_data['awaiting'] = ''


async def run_bot():
    init_db()
    logger.info("✅ Database ready")
    
    # Start all accounts from Environment Variables
    await start_all_accounts()
    
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
