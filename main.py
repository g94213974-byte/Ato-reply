# main.py
import asyncio
import os
import json
import logging
import random
import shutil
from threading import Thread
from time import sleep

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
from telethon.tl.functions.messages import ReadHistoryRequest, DeleteMessagesRequest
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count
from config import BOT_TOKEN, ADMIN_ID, ACCOUNTS, API_ID, API_HASH

# ===== AI MODULE IMPORT =====
from shruti_bot import ShrutiAIBot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return jsonify({"status": "running", "bot": "Shruti AI Bot", "accounts": len(accounts)})

@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200

# ===== GLOBAL VARIABLES =====
accounts = []
_welcomed_chats = set()
shruti_bot = ShrutiAIBot()
customer_message_count = {}
customer_payment_photos = {}
SESSION_FILE = "saved_sessions.json"

DEFAULT_PRICE_LIST = """💕 **SHRUTI'S PRICE LIST** 💕

📱 10 MIN VIDEO CALL → ₹49 🔥
📱 20 MIN VIDEO CALL → ₹59 💋
🎬 DEMO SHOW → ₹19 ONLY 😘

**💰 HOW TO PAY 💰**
Check my profile for payment details
Then send me the SCREENSHOT here baby!"""

# ===== SESSION MANAGEMENT =====
def _save_sessions():
    sessions = [acc['session'] for acc in accounts if 'session' in acc and acc['session']]
    with open(SESSION_FILE, 'w') as f:
        json.dump(sessions, f, indent=2)
    logger.info(f"💾 Saved {len(sessions)} sessions")

def _load_sessions():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load sessions: {e}")
    return []

# ===== ACCOUNT MANAGEMENT =====
async def start_single_account(session_string):
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
        await client.start()
        me = await client.get_me()
        
        acc_info = {
            'id': me.id,
            'name': me.first_name or f"User{me.id}",
            'client': client,
            'enabled': True,
            'mode': 'ai',
            'session': session_string
        }
        accounts.append(acc_info)
        _register_handler(client, acc_info)
        _save_sessions()
        logger.info(f"✅ Connected: {me.first_name} (ID: {me.id})")
        return acc_info
    except Exception as e:
        logger.error(f"❌ Account failed: {e}")
        return None

async def start_all_accounts():
    saved_sessions = _load_sessions()
    if saved_sessions:
        logger.info(f"🔄 Starting {len(saved_sessions)} saved accounts...")
        for session in saved_sessions:
            try:
                await start_single_account(session)
                await asyncio.sleep(2)
            except Exception as e:
                logger.error(f"Account failed: {e}")
    logger.info(f"✅ {len(accounts)} accounts connected!")

def _register_handler(client, acc_info):
    from telethon import events
    
    @client.on(events.NewMessage(incoming=True))
    async def auto_reply_handler(event):
        try:
            if not event.is_private:
                return
            sender = await event.get_sender()
            if sender is None:
                return
            sender_id = sender.id
            if sender_id == ADMIN_ID:
                return
            if not acc_info.get('enabled', True):
                return
            
            mode = acc_info.get('mode', 'ai')
            if mode == 'keyword':
                await handle_keyword_mode(event, client, acc_info)
            else:
                await handle_ai_mode(event, client, acc_info, sender_id)
        except Exception as e:
            logger.error(f"Handler error: {e}")

# ===== AI MODE HANDLER - FIXED VERSION =====
async def handle_ai_mode(event, client, acc_info, sender_id):
    try:
        msg_text = event.message.text or ""
        chat_id = event.chat_id
        
        if sender_id not in customer_message_count:
            customer_message_count[sender_id] = 0
        
        count = customer_message_count[sender_id]
        
        # ===== CHECK FOR PHOTO (PAYMENT SCREENSHOT) =====
        if event.message.photo:
            await handle_payment_screenshot(event, client, sender_id)
            return
        
        if not msg_text:
            return
        
        # ===== STEP 1: MARK MESSAGE AS SEEN (2 TICK) =====
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
            logger.info(f"✅ Message seen mark for user {sender_id}")
        except Exception as e:
            logger.warning(f"Could not mark seen: {e}")
        
        # ===== STEP 2: SMALL DELAY LIKE REAL HUMAN =====
        wait_time = random.uniform(1.0, 3.0)
        await asyncio.sleep(wait_time)
        
        # ===== STEP 3: TYPING INDICATOR + SMART DELAY =====
        async with client.action(chat_id, "typing"):
            # Calculate typing time based on message length and randomness
            typing_time = max(1.5, min(5.0, len(msg_text) * 0.08))
            typing_time = typing_time * random.uniform(0.7, 1.3)  # Add randomness
            await asyncio.sleep(typing_time)
            
            # ===== STEP 4: GET AI REPLY WITH FULL CONTEXT =====
            reply = shruti_bot.get_reply(sender_id, msg_text, count)
            
            # ===== STEP 5: SEND REPLY =====
            await event.respond(reply)
            logger.info(f"✅ Replied to user {sender_id}: {reply[:50]}...")
            
            # ===== STEP 6: SEND PRICE LIST ON 3RD MESSAGE =====
            if count == 2:
                await asyncio.sleep(1.0)
                price_image = get_setting('price_list_image', '')
                if price_image and os.path.exists(price_image):
                    try:
                        price_text = get_setting('price_list_text', DEFAULT_PRICE_LIST)
                        await client.send_file(chat_id, price_image, caption=price_text)
                    except:
                        await event.respond(get_setting('price_list_text', DEFAULT_PRICE_LIST))
                else:
                    await event.respond(get_setting('price_list_text', DEFAULT_PRICE_LIST))
            
            # ===== STEP 7: PAYMENT REMINDER EVERY 4-6 MESSAGES =====
            reminder_interval = random.randint(4, 6)
            if count >= 4 and count % reminder_interval == 0:
                await asyncio.sleep(0.8)
                reminders = [
                    "baby pay karo na... screenshot bhejo 😘",
                    "i am waiting for your payment baby 🔥",
                    "no time pass... pay and come 💕",
                    "pay karo na baby... screenshot bhejo 😈",
                    "kab pay karoge? main wait kar rahi hoon 😘",
                    "screenshot bhejo payment ka... confirm kar dungi 💕",
                    "baby please pay... then we can have real fun 🔥",
                    "tum pay karo... main ready hoon 😈"
                ]
                await event.respond(random.choice(reminders))
            
            # ===== STEP 8: UPDATE COUNTER =====
            customer_message_count[sender_id] = count + 1
    
    except Exception as e:
        logger.error(f"AI mode error: {e}")

# ===== PAYMENT SCREENSHOT HANDLER =====
async def handle_payment_screenshot(event, client, sender_id):
    try:
        photo = event.message.photo[-1]
        os.makedirs('payment_screenshots', exist_ok=True)
        file_path = f"payment_screenshots/{sender_id}_{event.message.id}.jpg"
        await photo.download_async(file_path)
        customer_payment_photos[sender_id] = file_path
        
        await event.respond(
            "🥰 **Payment screenshot received baby!** 🥰\n\n"
            "Main abhi **ADMIN** ko forward kar rahi hoon...\n"
            "Admin aapko 2 minute mein personally handle karega!\n\n"
            "**⏳ Please wait baby...** 😘🔥"
        )
        
        await client.send_message(
            ADMIN_ID,
            f"🚨 **NEW PAYMENT SCREENSHOT!** 🚨\n\n"
            f"👤 Customer: [{event.sender.first_name}](tg://user?id={sender_id})\n"
            f"🆔 User ID: `{sender_id}`\n"
            f"💬 Messages sent: {customer_message_count.get(sender_id, 0)}\n\n"
            f"🔴 **ADMIN PLEASE CHECK SCREENSHOT AND HANDLE!** 🔴",
            parse_mode='Markdown'
        )
        await client.send_file(ADMIN_ID, file_path)
        customer_message_count[sender_id] = -2
        logger.info(f"Payment screenshot received from user {sender_id}")
    except Exception as e:
        logger.error(f"Payment screenshot error: {e}")
        await event.respond("baby screenshot mil gaya... admin check karega thoda wait karo 💕")

# ===== KEYWORD MODE HANDLER =====
async def handle_keyword_mode(event, client, acc_info):
    try:
        msg_text = event.message.text or ""
        if not msg_text:
            return
        
        chat_id = event.chat_id
        msg_id = event.message.id
        sender = await event.get_sender()
        sender_id = sender.id
        
        is_photo = False
        if event.message.media:
            if isinstance(event.message.media, MessageMediaPhoto):
                is_photo = True
            elif isinstance(event.message.media, MessageMediaDocument):
                if hasattr(event.message.media, 'document') and event.message.media.document:
                    mime = (event.message.media.document.mime_type or '').lower()
                    if mime.startswith('image/') and 'webp' not in mime and 'sticker' not in mime:
                        is_photo = True
        
        if is_photo:
            block_photo = get_setting('block_photo_enabled', '1') == '1'
            if block_photo:
                try:
                    peer = await event.get_input_chat()
                    try:
                        await client(BlockRequest(id=sender_id))
                    except:
                        pass
                    await asyncio.sleep(0.3)
                    try:
                        await client.delete_messages(peer, [msg_id], revoke=True)
                    except:
                        pass
                    try:
                        async for msg in client.iter_messages(chat_id, limit=200):
                            try:
                                await client.delete_messages(peer, [msg.id], revoke=True)
                                await asyncio.sleep(0.1)
                            except:
                                pass
                    except:
                        pass
                except:
                    pass
            return
        
        # MARK AS SEEN
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=msg_id))
        except:
            pass
        
        typing_enabled = get_setting('typing_enabled', '1') == '1'
        typing_duration = int(get_setting('typing_duration', '5'))
        msg_lower = msg_text.lower().strip()
        replies = get_all_replies()
        matched = False
        
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
        
        if not matched:
            default_reply_enabled = get_setting('default_reply_enabled', '1') == '1'
            if not default_reply_enabled:
                return
            
            welcome_enabled = get_setting('welcome_enabled', '1') == '1'
            welcome_photo = get_setting('welcome_photo', '')
            default_photo = get_setting('default_photo', '')
            
            if chat_id not in _welcomed_chats and welcome_enabled:
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
                if typing_enabled:
                    async with client.action(event.chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                default_reply = get_setting('default_reply_text', '🤖 Main samajh gayi baby... but pay first na 😘')
                if default_photo and os.path.exists(default_photo):
                    try:
                        await client.send_file(event.chat_id, default_photo, caption=default_reply)
                    except:
                        await event.respond(default_reply)
                else:
                    await event.respond(default_reply)
    except Exception as e:
        logger.error(f"Keyword mode error: {e}")

# ===== MAIN MENU =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    connected = len(accounts)
    model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
    paid = sum(1 for v in customer_message_count.values() if v == -2)
    
    keyboard = [
        [InlineKeyboardButton("🤖 AI Mode Control", callback_data="menu_ai")],
        [InlineKeyboardButton("💰 Payment Methods", callback_data="menu_payment")],
        [InlineKeyboardButton("📋 Keyword Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("➕ Add Reply", callback_data="add_reply_keyword")],
        [InlineKeyboardButton("🗑 Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("👥 Account List", callback_data="menu_accounts")],
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account_how")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
    ]
    
    text = f"🤖 **Shruti's Control Panel** 🤖\n\n"
    text += f"🟢 Connected: {connected} accounts\n"
    text += f"💰 Paid today: {paid}\n"
    text += f"🧠 AI Model: {model}\n\n"
    text += "**নিচের বাটন থেকে সিলেক্ট করুন 👇**"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

# ===== MESSAGE HANDLER (Auto Open Main Menu) =====
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle any text or photo from admin - auto show menu"""
    if update.effective_user.id != ADMIN_ID:
        return
    
    user_data = context.user_data
    awaiting = user_data.get('awaiting', '')
    
    # If waiting for input (like UPI ID, keyword), process it
    if awaiting:
        if update.message.text:
            await handle_text_input(update, context)
        elif update.message.photo:
            await handle_photo_input(update, context)
        return
    
    # Check if this is a session string (for adding account)
    text = update.message.text or ""
    if text.startswith("1") and len(text) > 100:
        # Looks like a session string! Try to add account
        await add_account_from_message(update, context, text)
        return
    
    # Otherwise, delete the message and show menu
    try:
        await update.message.delete()
    except:
        pass
    
    await show_main_menu(update, context)

# ===== ADD ACCOUNT FROM MESSAGE =====
async def add_account_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session_string):
    """Auto detect session string and add account"""
    msg = await update.message.reply_text("⏳ **Account add করা হচ্ছে...**")
    
    try:
        await update.message.delete()
    except:
        pass
    
    try:
        acc_info = await start_single_account(session_string)
        
        await msg.edit_text(
            f"✅ **Account Added Successfully!** 🎉\n\n"
            f"👤 Name: {acc_info['name']}\n"
            f"🆔 ID: `{acc_info['id']}`\n"
            f"📊 Total: {len(accounts)} accounts\n\n"
            f"✅ এখন active আছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
    except Exception as e:
        await msg.edit_text(
            f"❌ **Failed!**\n\nError: `{str(e)[:200]}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )

# ===== TEXT INPUT HANDLER =====
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    awaiting = context.user_data.get('awaiting', '')
    
    # Delete the input message for cleanliness
    try:
        await update.message.delete()
    except:
        pass
    
    msg = None
    
    if awaiting == 'upi_id':
        set_setting('upi_id', text)
        context.user_data['awaiting'] = ''
        msg = f"✅ UPI ID saved: `{text}`"
    
    elif awaiting == 'paytm_num':
        set_setting('paytm_num', text)
        context.user_data['awaiting'] = ''
        msg = f"✅ PayTm saved: `{text}`"
    
    elif awaiting == 'prices':
        set_setting('price_list_text', text)
        context.user_data['awaiting'] = ''
        msg = "✅ Price list updated!"
    
    elif awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        
        kb = [
            [InlineKeyboardButton("🔑 Exact Match", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]
        ]
        
        await update.message.reply_text(
            f"Keyword: `{text}`\n\nMatch type select করুন:",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
        return
    
    elif awaiting == 'reply_text':
        kw = context.user_data.get('add_keyword', '')
        tp = context.user_data.get('reply_type', 'exact')
        rid = add_reply(kw, text, tp)
        context.user_data['awaiting'] = ''
        msg = f"✅ Reply added! (ID: {rid})"
    
    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        msg = "✅ Welcome text updated!"
    
    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        msg = "✅ Default reply updated!"
    
    if msg:
        await update.message.reply_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )

# ===== PHOTO INPUT HANDLER =====
async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get('awaiting', '')
    
    try:
        await update.message.delete()
    except:
        pass
    
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    if awaiting == 'qr_code':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/qr_code.jpg")
        set_setting('qr_code_path', "payment_assets/qr_code.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ QR Code saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif awaiting == 'price_image':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/price_list.jpg")
        set_setting('price_list_image', "payment_assets/price_list.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Price list image saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))

# ===== CALLBACK HANDLER (ALL BUTTONS) =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "main_menu":
        await update.effective_message.delete()
        await show_main_menu(update, context)
        return
    
    # ===== ADD ACCOUNT =====
    elif data == "add_account_how":
        await query.edit_message_text(
            "📱 **New Account Add করুন** 📱\n\n"
            "**Step 1:** Termux/PC/Laptop এ নিচের command চালান:\n\n"
            "```\n"
            "pip install telethon && python -c \"from telethon.sync import TelegramClient; from telethon.sessions import StringSession; c = TelegramClient(StringSession(), 37362415, '88f99afa3b9a81adce62267b701e7b9f'); c.start(); print(c.session.save())\"\n"
            "```\n\n"
            "**Step 2:** যে String print হবে, সেটা **copy** করুন\n\n"
            "**Step 3:** সেই String টা এই chat এ **paste করে send করুন**\n\n"
            "**বট automatic detect করে account add করে নিবে!** ✅",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
    
    # ===== ACCOUNT LIST =====
    elif data == "menu_accounts":
        if not accounts:
            await query.edit_message_text(
                "👥 **কোনো Account নেই!**",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Add Account", callback_data="add_account_how")],
                    [InlineKeyboardButton("🔙", callback_data="main_menu")]
                ]),
                parse_mode='Markdown'
            )
            return
        
        msg = f"👥 **Total Accounts: {len(accounts)}**\n\n"
        kb = []
        
        for i, acc in enumerate(accounts):
            s = "🟢" if acc.get('enabled', True) else "🔴"
            mode = "🤖AI" if acc.get('mode') == 'ai' else "📋KW"
            name = acc.get('name', f"User{acc['id']}")
            msg += f"{s} #{i+1} {name} [{mode}]\n"
            kb.append([InlineKeyboardButton(
                f"{'🔴 Disable' if acc.get('enabled', True) else '🟢 Enable'} #{i+1}",
                callback_data=f"tog_{i}"
            )])
        
        kb.append([InlineKeyboardButton("➕ Add New", callback_data="add_account_how")])
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith("tog_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            accounts[idx]['enabled'] = not accounts[idx].get('enabled', True)
            _save_sessions()
        await button_callback(update, context)
    
    # ===== AI MODE =====
    elif data == "menu_ai":
        ai_count = sum(1 for a in accounts if a.get('mode') == 'ai')
        active = len([k for k,v in customer_message_count.items() if 0 < v < 15])
        paid = sum(1 for v in customer_message_count.values() if v == -2)
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        
        msg = f"🤖 **AI Mode Control**\n\n"
        msg += f"AI Mode: {ai_count}/{len(accounts)} accounts\n"
        msg += f"Active customers: {active}\n"
        msg += f"Paid today: {paid}\n"
        msg += f"Model: `{model}`\n\n"
        msg += "AI mode এ Shruti নিজে কথা বলবে!"
        
        kb = [
            [InlineKeyboardButton("🟢 Start AI Mode", callback_data="ai_start")],
            [InlineKeyboardButton("🔴 Stop AI (Keyword)", callback_data="ai_stop")],
            [InlineKeyboardButton("📊 Stats", callback_data="ai_stats")],
            [InlineKeyboardButton("🔄 Reset Counters", callback_data="reset_counters")],
            [InlineKeyboardButton("⚡ Change AI Model", callback_data="change_model")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "ai_start":
        for acc in accounts:
            acc['mode'] = 'ai'
        await query.edit_message_text(
            "✅ **AI Mode Started!** 🥰\n\nসব account AI mode এ আছে!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]),
            parse_mode='Markdown'
        )
    
    elif data == "ai_stop":
        for acc in accounts:
            acc['mode'] = 'keyword'
        await query.edit_message_text(
            "✅ **Keyword Mode Started!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]])
        )
    
    elif data == "ai_stats":
        active = len([k for k,v in customer_message_count.items() if 0 < v < 15])
        paid = sum(1 for v in customer_message_count.values() if v == -2)
        blocked = sum(1 for v in customer_message_count.values() if v >= 15)
        screenshots = len([f for f in os.listdir('payment_screenshots')]) if os.path.exists('payment_screenshots') else 0
        
        msg = f"📊 **CUSTOMER STATS**\n\n"
        msg += f"👤 Active: {active}\n"
        msg += f"💰 Paid (pending): {paid}\n"
        msg += f"🚫 Blocked: {blocked}\n"
        msg += f"📸 Screenshots: {screenshots}\n"
        msg += f"👥 Accounts: {len(accounts)}"
        
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]),
            parse_mode='Markdown'
        )
    
    elif data == "reset_counters":
        customer_message_count.clear()
        await query.edit_message_text(
            "✅ All counters reset!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]])
        )
    
    elif data == "change_model":
        kb = [
            [InlineKeyboardButton("🟢 GPT-4o Mini", callback_data="model_openai/gpt-4o-mini")],
            [InlineKeyboardButton("🔵 GPT-4o", callback_data="model_openai/gpt-4o")],
            [InlineKeyboardButton("🟣 Gemini 2.0 Flash", callback_data="model_google/gemini-2.0-flash-exp")],
            [InlineKeyboardButton("🟠 Llama 3.3 70B", callback_data="model_meta-llama/llama-3.3-70b-instruct")],
            [InlineKeyboardButton("🔙", callback_data="menu_ai")]
        ]
        await query.edit_message_text(
            "⚡ **Select AI Model**",
            reply_markup=InlineKeyboardMarkup(kb),
            parse_mode='Markdown'
        )
    
    elif data.startswith("model_"):
        model = data.replace("model_", "")
        set_setting('openrouter_model', model)
        await query.edit_message_text(
            f"✅ Model: `{model}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]),
            parse_mode='Markdown'
        )
    
    # ===== PAYMENT =====
    elif data == "menu_payment":
        current_upi = get_setting('upi_id', 'Not set')
        current_paytm = get_setting('paytm_num', 'Not set')
        has_qr = os.path.exists(get_setting('qr_code_path', '')) if get_setting('qr_code_path', '') else False
        
        msg = f"💰 **PAYMENT METHODS**\n\n"
        msg += f"📱 UPI: `{current_upi}`\n"
        msg += f"💳 PayTm: `{current_paytm}`\n"
        msg += f"🖼️ QR: {'✅' if has_qr else '❌'}\n\n"
        msg += "AI payment info direct দেবে না!\nশুধু screenshot চাইবে!"
        
        kb = [
            [InlineKeyboardButton("📱 Set UPI ID", callback_data="set_upi")],
            [InlineKeyboardButton("💳 Set PayTm", callback_data="set_paytm")],
            [InlineKeyboardButton("🖼️ Upload QR Code", callback_data="upload_qr")],
            [InlineKeyboardButton("💰 Edit Price List", callback_data="edit_prices")],
            [InlineKeyboardButton("🖼️ Price List Image", callback_data="upload_price_image")],
            [InlineKeyboardButton("📊 Screenshots", callback_data="view_screenshots")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "set_upi":
        context.user_data['awaiting'] = 'upi_id'
        await query.edit_message_text(
            "📝 **UPI ID লিখুন:**\n\nExample: `shruti@paytm`\n\n**এখন মেসেজ আকারে UPI ID পাঠান:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]),
            parse_mode='Markdown'
        )
    
    elif data == "set_paytm":
        context.user_data['awaiting'] = 'paytm_num'
        await query.edit_message_text(
            "💳 **PayTm Number লিখুন:**\n\nExample: `9876543210`\n\n**এখন মেসেজ আকারে Number পাঠান:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]),
            parse_mode='Markdown'
        )
    
    elif data == "upload_qr":
        context.user_data['awaiting'] = 'qr_code'
        await query.edit_message_text(
            "🖼️ **QR Code পাঠান:**\n\nএখন QR code এর PHOTO পাঠান!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]])
        )
    
    elif data == "edit_prices":
        context.user_data['awaiting'] = 'prices'
        current_price = get_setting('price_list_text', DEFAULT_PRICE_LIST)
        await query.edit_message_text(
            f"💰 **Edit Price List**\n\n**Current:**\n{current_price}\n\n**নতুন price list টেক্সট পাঠান:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]),
            parse_mode='Markdown'
        )
    
    elif data == "upload_price_image":
        context.user_data['awaiting'] = 'price_image'
        await query.edit_message_text(
            "🖼️ **Price List Image পাঠান:**\n\nPrice list এর PHOTO পাঠান!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]])
        )
    
    elif data == "view_screenshots":
        screenshots = os.listdir('payment_screenshots') if os.path.exists('payment_screenshots') else []
        msg = f"📊 **SCREENSHOTS**\n\nTotal: {len(screenshots)}\n\n"
        if screenshots:
            msg += "Last 5:\n"
            for s in screenshots[-5:]:
                user_id = s.split('_')[0]
                msg += f"👤 User: {user_id}\n"
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🗑️ Clear All", callback_data="clear_screenshots")],
                [InlineKeyboardButton("🔙", callback_data="menu_payment")]
            ]),
            parse_mode='Markdown'
        )
    
    elif data == "clear_screenshots":
        if os.path.exists('payment_screenshots'):
            shutil.rmtree('payment_screenshots')
            os.makedirs('payment_screenshots', exist_ok=True)
        await query.edit_message_text("✅ All screenshots cleared!")
    
    # ===== REPLIES =====
    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 No keyword replies!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]])
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
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data.startswith("rp_"):
        context.user_data['reply_page'] = int(data.split("_")[1])
        await button_callback(update, context)
    
    elif data == "add_reply_keyword":
        context.user_data['awaiting'] = 'keyword'
        await query.edit_message_text(
            "➕ **Reply যোগ করুন**\n\nযে keyword এ reply দিতে হবে, সেটা লিখুন:\n\n(এখন মেসেজ আকারে keyword পাঠান)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
    
    elif data == "reply_type_exact":
        context.user_data['reply_type'] = 'exact'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text(
            "➕ **Reply Text লিখুন:**\n\nএখন reply টেক্সট পাঠান:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
    
    elif data == "reply_type_contains":
        context.user_data['reply_type'] = 'contains'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text(
            "➕ **Reply Text লিখুন:**\n\nএখন reply টেক্সট পাঠান:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )
    
    elif data == "menu_del_reply":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text(
                "📭 No replies!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]])
            )
            return
        kb = []
        for r in replies[:10]:
            rid, kw, _, tp = r
            e = "🔑" if tp == "exact" else "🔍"
            kb.append([InlineKeyboardButton(f"{e} ID:{rid} {kw[:20]}", callback_data=f"cd_{rid}")])
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text("🗑 **Delete Reply**\n\nSelect করুন:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("cd_"):
        rid = int(data.split("_")[1])
        await query.edit_message_text(
            f"⚠️ Delete ID {rid}?",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ হ্যাঁ", callback_data=f"dd_{rid}")],
                [InlineKeyboardButton("❌ না", callback_data="menu_del_reply")]
            ])
        )
    
    elif data.startswith("dd_"):
        rid = int(data.split("_")[1])
        if delete_reply(rid):
            await query.edit_message_text(
                "✅ Deleted!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]])
            )
        else:
            await query.edit_message_text("❌ Not found!")
    
    # ===== SETTINGS =====
    elif data == "menu_settings":
        w = '✅' if get_setting('welcome_enabled','1')=='1' else '❌'
        bp = '✅' if get_setting('block_photo_enabled','1')=='1' else '❌'
        t = '✅' if get_setting('typing_enabled','1')=='1' else '❌'
        tt = int(get_setting('typing_duration','5'))
        dr = '✅' if get_setting('default_reply_enabled','1')=='1' else '❌'
        
        kb = [
            [InlineKeyboardButton(f"👋 Welcome {w}", callback_data="tw")],
            [InlineKeyboardButton("✏️ Welcome Text", callback_data="swt")],
            [InlineKeyboardButton(f"📸 Block Photo {bp}", callback_data="tbp")],
            [InlineKeyboardButton(f"⌨️ Typing {t}", callback_data="tty")],
            [InlineKeyboardButton(f"⏱️ Typing {tt}s", callback_data="stt")],
            [InlineKeyboardButton(f"💬 Default Reply {dr}", callback_data="tdr")],
            [InlineKeyboardButton("✏️ Default Text", callback_data="sdrt")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text("⚙️ **Settings**", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "tw":
        cur = get_setting('welcome_enabled','1')
        set_setting('welcome_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    
    elif data == "swt":
        context.user_data['awaiting'] = 'welcome_text'
        await query.edit_message_text("✏️ **Welcome Message লিখুন:**\n\nএখন মেসেজ আকারে পাঠান:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
    
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
        kb = [
            [InlineKeyboardButton("5s", callback_data="tt_5"), InlineKeyboardButton("10s", callback_data="tt_10")],
            [InlineKeyboardButton("15s", callback_data="tt_15"), InlineKeyboardButton("30s", callback_data="tt_30")],
            [InlineKeyboardButton("60s", callback_data="tt_60")],
            [InlineKeyboardButton("🔙", callback_data="menu_settings")]
        ]
        await query.edit_message_text(f"⏱️ Current: {current}s\n\nSelect duration:", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("tt_"):
        sec = int(data.split("_")[1])
        set_setting('typing_duration', str(sec))
        await button_callback(update, context)
    
    elif data == "tdr":
        cur = get_setting('default_reply_enabled','1')
        set_setting('default_reply_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    
    elif data == "sdrt":
        context.user_data['awaiting'] = 'default_reply_text'
        await query.edit_message_text("✏️ **Default Reply Text লিখুন:**\n\nএখন মেসেজ আকারে পাঠান:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
    
    # ===== STATUS =====
    elif data == "menu_status":
        w = '✅' if get_setting('welcome_enabled','1')=='1' else '❌'
        bp = '✅' if get_setting('block_photo_enabled','1')=='1' else '❌'
        t = '✅' if get_setting('typing_enabled','1')=='1' else '❌'
        tt = int(get_setting('typing_duration','5'))
        dr = '✅' if get_setting('default_reply_enabled','1')=='1' else '❌'
        ai_active = sum(1 for a in accounts if a.get('mode')=='ai')
        paid = sum(1 for v in customer_message_count.values() if v == -2)
        active_cust = len([k for k,v in customer_message_count.items() if 0 < v < 15])
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        
        accs = "\n".join([f"{'🟢' if a.get('enabled',True) else '🔴'} #{i+1} {a['name']} {'🤖' if a.get('mode')=='ai' else '📋'}" for i,a in enumerate(accounts)]) or "No accounts"
        
        msg = f"📊 **FULL STATUS**\n\n"
        msg += f"👥 Total Accounts: {len(accounts)}\n{accs}\n\n"
        msg += f"🤖 AI Mode: {ai_active}/{len(accounts)}\n"
        msg += f"🧠 Model: `{model}`\n"
        msg += f"👤 Active customers: {active_cust}\n"
        msg += f"💰 Paid: {paid}\n"
        msg += f"📝 Keyword Replies: {get_reply_count()}\n"
        msg += f"👋 Welcome: {w} | 📸 Block: {bp}\n"
        msg += f"⌨️ Typing: {t} | ⏱️ {tt}s\n"
        msg += f"💬 Default: {dr}"
        
        await query.edit_message_text(
            msg,
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]),
            parse_mode='Markdown'
        )

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")

# ===== BOT RUNNER =====
async def run_bot():
    init_db()
    logger.info("✅ Database ready")
    await start_all_accounts()
    
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    try:
        await bot.delete_webhook()
        logger.info("✅ Old webhook deleted")
    except:
        pass
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ONLY ONE HANDLER - Message handler for everything
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    await app.initialize()
    await app.start()
    logger.info("✅ Bot started!")
    await app.updater.start_polling()
    logger.info("✅ Polling started!")
    
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
    bot_thread = Thread(target=lambda: loop.run_until_complete(run_bot()), daemon=True)
    bot_thread.start()
    sleep(3)
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, use_reloader=False)

if __name__ == "__main__":
    run_main()
