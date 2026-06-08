import asyncio
import os
import json
import logging
import random
import shutil
import signal
import subprocess
from threading import Thread
from time import sleep

from flask import Flask, jsonify
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import Conflict

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.messages import ReadHistoryRequest
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count
from config import BOT_TOKEN, ADMIN_ID, ACCOUNTS, API_ID, API_HASH

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
customer_message_count = {}
customer_payment_photos = {}
SESSION_FILE = "saved_sessions.json"

DEFAULT_PRICE_LIST = """💰 **SHRUTI PRICE LIST** 💰

🔥 10 MIN VC → ₹99
🔥 20 MIN VC → ₹119
🎬 DEMO (2 MIN FULL NUDE) → ₹49

💳 **Pay karo baby, phir maza lo!** 😘"""

SERVICE_KEYWORDS = ['service', 'servic', 'survice', 'sarvice', 'lena hai', 'chahiye', 'kharid', 
                    'leni hai', 'demo', 'video', 'call', 'vc', 'price', 'rate', 'kya milega',
                    'kya service', 'kaam', 'kya hai', 'dikhao', 'show']

PAYMENT_KEYWORDS = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'phonepe', 'gpay', 
                    'google pay', 'kaha', 'kaise', 'account', 'bank', 'send', 'bhejo',
                    'screenshot', 'payment kar', 'pay karo', 'kaise pay', 'method', 'transfer',
                    'rupees', 'rs', '₹', 'dham', 'send karo', 'money', 'paise', 'payment method',
                    'payment kaise', 'kaha karu']

PHOTO_BLOCK_KEYWORDS = ['pic', 'pics', 'picture', 'photo', 'image', 'nude pic', 'nude photo',
                        'naked', 'xxx pic', 'sexy pic', 'dikhao', 'show', 'full nude',
                        'nangi', 'boob', 'boobs', 'dikha', 'mms', 'xnxx', 'xxx',
                        'nude video', 'sex video', 'blue film', 'bf', 'xxx video']

# Shruti AI bot instance
shruti_bot = None

def get_ai_bot():
    global shruti_bot
    if shruti_bot is None:
        try:
            shruti_bot = ShrutiAIBot()
            logger.info("✅ Shruti AI Bot initialized")
        except Exception as e:
            logger.error(f"❌ Failed to init AI bot: {e}")
    return shruti_bot

# ===== SESSION MANAGEMENT =====
def _save_sessions():
    sessions = [acc['session'] for acc in accounts if 'session' in acc and acc['session']]
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump(sessions, f, indent=2)
    except Exception as e:
        logger.error(f"Session save error: {e}")

def _load_sessions():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Session load error: {e}")
    return []

# ===== ACCOUNT MANAGEMENT =====
async def start_single_account(session_string):
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH, sequential_updates=True)
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
                logger.error(f"Account start error: {e}")
    logger.info(f"✅ {len(accounts)} accounts connected!")

def _register_handler(client, acc_info):
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

# ===== TYPING HELPER =====
async def do_typing(client, chat_id):
    try:
        typing_enabled = get_setting('typing_enabled', '1') == '1'
        if not typing_enabled:
            await asyncio.sleep(0.3)
            return
        
        typing_duration = int(get_setting('typing_duration', '3'))
        
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(typing_duration)
    except Exception as e:
        logger.error(f"Typing error: {e}")
        await asyncio.sleep(0.3)

# ===== SEND PAYMENT QR HELPER (FIXED) =====
async def send_payment_info(client, chat_id, event=None):
    try:
        upi_id = get_setting('upi_id', '')
        paytm_num = get_setting('paytm_num', '')
        qr_path = get_setting('qr_code_path', '')
        
        payment_msg = "**💰 Payment Details 💰**\n\n"
        if upi_id:
            payment_msg += f"📱 **UPI ID:** `{upi_id}`\n"
        if paytm_num:
            payment_msg += f"💳 **PayTm:** `{paytm_num}`\n"
        payment_msg += "\n**Scan karo baby, payment karo 😘🔥**"
        
        qr_exists = qr_path and os.path.exists(qr_path)
        
        if qr_exists:
            try:
                await client.send_file(chat_id, qr_path, caption=payment_msg)
                logger.info(f"✅ QR sent to {chat_id}")
                return
            except Exception as e:
                logger.error(f"QR send error: {e}")
                await event.respond(payment_msg)
        else:
            full_msg = payment_msg + "\n\n⚠️ **QR code set nahi hai! Admin se set karwao**"
            await event.respond(full_msg)
            
    except Exception as e:
        logger.error(f"Payment info error: {e}")

# ===== PHOTO BLOCK HANDLER =====
async def handle_photo_block(event, client, sender_id):
    try:
        logger.info(f"📸 Photo block initiated for {sender_id}")
        
        peer = await event.get_input_chat()
        chat_id = event.chat_id
        
        try:
            await client.delete_messages(peer, [event.message.id], revoke=True)
            logger.info(f"✅ Photo message deleted for {sender_id}")
        except Exception as e:
            logger.error(f"Delete photo msg error: {e}")
        
        try:
            async for msg in client.iter_messages(peer, limit=100):
                try:
                    await client.delete_messages(peer, [msg.id], revoke=True)
                except:
                    pass
            logger.info(f"✅ Chat history cleared for {sender_id}")
        except Exception as e:
            logger.warning(f"⚠️ Could not delete all messages: {e}")
        
        try:
            await client.delete_dialog(peer)
            logger.info(f"✅ Entire dialog deleted for {sender_id}")
        except Exception as e:
            logger.warning(f"⚠️ Dialog delete error: {e}")
        
        await asyncio.sleep(1)
        
        try:
            await client(BlockRequest(id=sender_id))
            logger.info(f"✅ User {sender_id} blocked!")
        except Exception as e:
            logger.error(f"Block error: {e}")
        
        try:
            await client(DeleteContactsRequest(id=[sender_id]))
            logger.info(f"✅ User {sender_id} removed from contacts")
        except:
            pass
        
        logger.info(f"✅ Photo block COMPLETE for {sender_id}")
        return True
    except Exception as e:
        logger.error(f"Photo block error: {e}")
        return False

# ===== WELCOME MESSAGE SENDER =====
async def send_welcome(client, chat_id):
    """পাঠাবে ওয়েলকাম মেসেজ + ফোটো (যদি সেট করা থাকে)"""
    try:
        welcome_text = get_setting('welcome_message', '')
        welcome_image = get_setting('welcome_image', '')
        
        if not welcome_text:
            welcome_text = "💰 **SHRUTI PRICE LIST** 💰\n\n🔥 10 MIN VC → ₹99\n🔥 20 MIN VC → ₹119\n🎬 DEMO (2 MIN FULL NUDE) → ₹49\n\n💳 **Pay karo baby, phir maza lo!** 😘"
        
        if welcome_image and os.path.exists(welcome_image):
            try:
                await client.send_file(chat_id, welcome_image, caption=welcome_text)
                logger.info(f"✅ Welcome with image sent to {chat_id}")
                return
            except:
                pass
        
        await client.send_message(chat_id, welcome_text)
        logger.info(f"✅ Welcome message sent to {chat_id}")
    except Exception as e:
        logger.error(f"Welcome send error: {e}")

# ===== AI MODE (FIXED - Welcome on first message, no duplicate) =====
async def handle_ai_mode(event, client, acc_info, sender_id):
    try:
        msg_text = event.message.text or ""
        chat_id = event.chat_id
        
        # ===== STICKER HANDLER =====
        if event.message.sticker:
            logger.info(f"🎴 Sticker from {sender_id}")
            if sender_id not in customer_message_count:
                customer_message_count[sender_id] = 0
            await do_typing(client, chat_id)
            await send_welcome(client, chat_id)
            customer_message_count[sender_id] += 1
            return
        
        # ===== PHOTO/MEDIA HANDLER =====
        if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
            block_enabled = get_setting('block_photo_enabled', '1') == '1'
            if block_enabled:
                await handle_photo_block(event, client, sender_id)
            else:
                await handle_payment_screenshot(event, client, sender_id)
            return
        
        # ===== TEXT MESSAGE =====
        if not msg_text.strip():
            return
        
        # ট্র্যাক করা শুরু করি
        if sender_id not in customer_message_count:
            customer_message_count[sender_id] = 0
        
        count = customer_message_count[sender_id]
        
        # ⭐ FIRST MESSAGE → শুধু ওয়েলকাম পাঠাবে, অন্য কিছু নয়
        if count == 0:
            logger.info(f"👋 First message from {sender_id} - sending welcome only")
            await do_typing(client, chat_id)
            await send_welcome(client, chat_id)
            customer_message_count[sender_id] = 1
            return
        
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
        except:
            pass
        
        msg_lower = msg_text.lower().strip()
        
        # ===== CUSTOM REPLIES CHECK =====
        replies = get_all_replies()
        custom_match = None
        
        for rid, keyword, reply_text, rtype in replies:
            kw = keyword.lower().strip()
            if rtype == "exact" and msg_lower == kw:
                custom_match = reply_text
                logger.info(f"✅ Custom reply matched (exact): '{kw}'")
                break
            elif rtype == "contains" and kw in msg_lower:
                custom_match = reply_text
                logger.info(f"✅ Custom reply matched (contains): '{kw}'")
                break
        
        if custom_match:
            await do_typing(client, chat_id)
            await event.respond(custom_match)
            customer_message_count[sender_id] = count + 1
            return
        
        # ===== PAYMENT QUESTION CHECK =====
        is_payment = any(kw in msg_lower for kw in PAYMENT_KEYWORDS + ['kaha kar', 'kisme kar', 'kaise kar', 'kaha pay', 'kaise pay',
                                     'kaha bhej', 'kaise bhej', 'method', 'scan', 'qr', 'upi id',
                                     'kya hai', 'kaha hai'])
        
        if is_payment:
            logger.info(f"💰 Payment query from {sender_id}")
            await do_typing(client, chat_id)
            await send_payment_info(client, chat_id, event)
            customer_message_count[sender_id] = count + 1
            return
        
        # ===== PHOTO BLOCK KEYWORDS (TEXT) =====
        if any(kw in msg_lower for kw in PHOTO_BLOCK_KEYWORDS):
            await do_typing(client, chat_id)
            await event.respond("Payment karo baby, phir maza lo 😘🔥 Service ready hai! 💯")
            customer_message_count[sender_id] = count + 1
            return
        
        # ===== SERVICE KEYWORDS =====
        is_service = any(kw in msg_lower for kw in SERVICE_KEYWORDS)
        if is_service:
            await do_typing(client, chat_id)
            price_text = get_setting('price_list_text', DEFAULT_PRICE_LIST)
            price_image = get_setting('price_list_image', '')
            if price_image and os.path.exists(price_image):
                await client.send_file(chat_id, price_image, caption=price_text)
            else:
                await event.respond(price_text)
            await asyncio.sleep(0.5)
            await event.respond(random.choice([
                "Bolo kitna time chahiye? 10 min ya 20 min? 🔥",
                "Pay karo baby, ready hoon main! 😘",
                "Payment karo, phir maza lo! 💯"
            ]))
            customer_message_count[sender_id] = count + 1
            return
        
        # ===== REAL MEET CHECK =====
        meet_keywords = ['real', 'meet', 'mil', 'real meet', 'aao', 'aana', 'ghar', 'location',
                        'aaja', 'offline', 'face to face', 'real video', 'milna', 'live']
        if any(kw in msg_lower for kw in meet_keywords):
            await do_typing(client, chat_id)
            await event.respond("Only online service baby 😊 Payment karo, ready hoon! 🔥")
            customer_message_count[sender_id] = count + 1
            return
        
        # ===== NORMAL AI REPLY (Payment please বাদ, service ready বলবে) =====
        await do_typing(client, chat_id)
        try:
            ai_bot = get_ai_bot()
            reply = None
            if ai_bot:
                reply = ai_bot.get_reply(sender_id, msg_text, count)
            if not reply:
                reply = get_service_ready_reply(msg_lower, count)
        except:
            reply = get_service_ready_reply(msg_lower, count)
        
        if reply:
            await event.respond(reply)
        
        customer_message_count[sender_id] = count + 1
    
    except Exception as e:
        logger.error(f"AI mode error: {e}", exc_info=True)
        try:
            await event.respond("Ready hoon baby, payment karo! 😘🔥")
        except:
            pass

# ===== SERVICE READY REPLY GENERATOR (No "please pay") =====
def get_service_ready_reply(msg_lower, count):
    """প্লিজ পেমেন্ট না বলে সার্ভিস রেডি বলবে"""
    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo', 'helo']):
        return random.choice([
            "Haan baby, ready hoon! 🔥 Kitna time chahiye?",
            "Hmm baby, kya chahiye? 😘",
            "Hi baby, ready hoon main! Batao kya lena hai? 🔥"
        ])
    return random.choice([
        "Ready hoon baby, payment karo, maza lo! 🔥",
        "Main ready hoon, tum payment karo! 😘",
        "Service ready hai baby, payment karo! 💯",
        "Batao kitna minute chahiye, payment karo! 🔥",
        "Ready baby! Payment karo, phir maza lo! 😘"
    ])

# ===== PAYMENT SCREENSHOT HANDLER =====
async def handle_payment_screenshot(event, client, sender_id):
    try:
        if event.message.photo:
            photo = event.message.photo[-1]
        elif event.message.document:
            photo = event.message.document
        else:
            return
        
        os.makedirs('payment_screenshots', exist_ok=True)
        file_path = f"payment_screenshots/{sender_id}_{event.message.id}.jpg"
        await photo.download_async(file_path)
        customer_payment_photos[sender_id] = file_path
        
        sender_name = event.sender.first_name if event.sender else "Unknown"
        
        await event.respond(
            "🥰 **Payment screenshot received baby!** 🥰\n\n"
            "Main abhi **ADMIN** ko forward kar rahi hoon...\n"
            "Admin aapko 2 minute mein personally handle karega!\n\n"
            "**⏳ Please wait baby...** 😘🔥"
        )
        
        await client.send_message(
            ADMIN_ID,
            f"🚨 **NEW PAYMENT!** 🚨\n\n"
            f"👤 Customer: [{sender_name}](tg://user?id={sender_id})\n"
            f"🆔 ID: `{sender_id}`\n"
            f"💬 Messages: {customer_message_count.get(sender_id, 0)}\n\n"
            f"🔴 **ADMIN CHECK!** 🔴",
            parse_mode='Markdown'
        )
        await client.send_file(ADMIN_ID, file_path)
        customer_message_count[sender_id] = -2
        logger.info(f"Payment screenshot from {sender_id}")
    except Exception as e:
        logger.error(f"Screenshot error: {e}")

# ===== KEYWORD MODE HANDLER =====
async def handle_keyword_mode(event, client, acc_info):
    try:
        msg_text = event.message.text or ""
        chat_id = event.chat_id
        
        sender_id = event.sender.id
        
        if event.message.photo:
            block_enabled = get_setting('block_photo_enabled', '1') == '1'
            if block_enabled:
                await handle_photo_block(event, client, event.sender.id)
            return
        
        if not msg_text.strip():
            return
        
        # প্রথম মেসেজ ওয়েলকাম
        if sender_id not in customer_message_count:
            customer_message_count[sender_id] = 0
        
        count = customer_message_count[sender_id]
        
        if count == 0:
            await do_typing(client, chat_id)
            await send_welcome(client, chat_id)
            customer_message_count[sender_id] = 1
            return
        
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
        except:
            pass
        
        await do_typing(client, chat_id)
        
        msg_lower = msg_text.lower().strip()
        replies = get_all_replies()
        matched = False
        
        for rid, keyword, reply_text, rtype in replies:
            kw = keyword.lower().strip()
            if rtype == "exact" and msg_lower == kw:
                matched = True
                await event.respond(reply_text)
                logger.info(f"✅ Keyword mode matched: {kw}")
                break
            elif rtype == "contains" and kw in msg_lower:
                matched = True
                await event.respond(reply_text)
                logger.info(f"✅ Keyword mode matched: {kw}")
                break
        
        if not matched:
            payment_question_keywords = ['kaha kar', 'kisme kar', 'kaise kar', 'kaha pay', 'kaise pay',
                                         'kaha bhej', 'kaise bhej', 'method', 'scan', 'qr', 'upi id']
            if any(kw in msg_lower for kw in payment_question_keywords):
                await send_payment_info(client, chat_id, event)
            elif get_setting('default_reply_enabled', '0') == '1':
                default_reply = get_setting('default_reply_text', 'Ready hoon baby, payment karo! 🔥')
                await event.respond(default_reply)
        
        customer_message_count[sender_id] = count + 1
    except Exception as e:
        logger.error(f"Keyword mode error: {e}")

# ===== ADMIN BOT HANDLERS =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    connected = len(accounts)
    model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
    
    keyboard = [
        [InlineKeyboardButton("🤖 AI Mode", callback_data="menu_ai")],
        [InlineKeyboardButton("💰 Payment", callback_data="menu_payment")],
        [InlineKeyboardButton("👋 Welcome", callback_data="menu_welcome")],
        [InlineKeyboardButton("📋 Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("➕ Add Reply", callback_data="add_reply_keyword")],
        [InlineKeyboardButton("🗑 Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("👥 Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("➕ Add Account", callback_data="add_account_how")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("📊 Status", callback_data="menu_status")],
    ]
    
    text = f"🤖 **Shruti's Panel** 🤖\n\n"
    text += f"🟢 Connected: {connected}\n"
    text += f"🧠 Model: {model}\n\n"
    text += "**Select করুন 👇**"
    
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    
    user_data = context.user_data
    awaiting = user_data.get('awaiting', '')
    
    if awaiting:
        if update.message.text:
            await handle_text_input(update, context)
        elif update.message.photo:
            await handle_photo_input(update, context)
        return
    
    text = update.message.text or ""
    if len(text) > 100:
        await add_account_from_message(update, context, text)
        return
    
    await show_main_menu(update, context)

async def add_account_from_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session_string):
    msg = await update.message.reply_text("⏳ **Adding...**")
    try:
        acc_info = await start_single_account(session_string)
        await msg.edit_text(f"✅ **Added!** 🎉\n👤 {acc_info['name']}\n🆔 `{acc_info['id']}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]), parse_mode='Markdown')
    except Exception as e:
        await msg.edit_text(f"❌ Failed: `{str(e)[:200]}`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))

async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    awaiting = context.user_data.get('awaiting', '')
    kb_back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]])
    
    if awaiting == 'upi_id':
        set_setting('upi_id', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ UPI: `{text}`", reply_markup=kb_back, parse_mode='Markdown')
    elif awaiting == 'paytm_num':
        set_setting('paytm_num', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ PayTm: `{text}`", reply_markup=kb_back, parse_mode='Markdown')
    elif awaiting == 'prices':
        set_setting('price_list_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Price list updated!", reply_markup=kb_back)
    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Welcome message updated!", reply_markup=kb_back)
    elif awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        kb = [
            [InlineKeyboardButton("🔑 Exact", callback_data="reply_type_exact")],
            [InlineKeyboardButton("🔍 Contains", callback_data="reply_type_contains")],
            [InlineKeyboardButton("🔙 Cancel", callback_data="main_menu")]
        ]
        await update.message.reply_text(f"Keyword: `{text}`\n\nMatch type:", reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
        return
    elif awaiting == 'reply_text':
        kw = context.user_data.get('add_keyword', '')
        tp = context.user_data.get('reply_type', 'exact')
        rid = add_reply(kw, text, tp)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"✅ Reply added! (ID: {rid})", reply_markup=kb_back)
    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Default reply updated!", reply_markup=kb_back)

async def handle_photo_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get('awaiting', '')
    photo = update.message.photo[-1]
    file = await photo.get_file()
    
    if awaiting == 'qr_code':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/qr_code.jpg")
        set_setting('qr_code_path', "payment_assets/qr_code.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ QR saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    elif awaiting == 'price_image':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/price_list.jpg")
        set_setting('price_list_image', "payment_assets/price_list.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Price list image saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    elif awaiting == 'welcome_image':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/welcome_image.jpg")
        set_setting('welcome_image', "payment_assets/welcome_image.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Welcome image saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))

# ===== CALLBACK HANDLER =====
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if data == "main_menu":
        await show_main_menu(update, context)
        return
    
    elif data == "add_account_how":
        await query.edit_message_text(
            "📱 **Add Account** 📱\n\n"
            "Command চালিয়ে String নাও:\n\n"
            "```\npip install telethon && python -c \"from telethon.sync import TelegramClient; from telethon.sessions import StringSession; c = TelegramClient(StringSession(), 37362415, '88f99afa3b9a81adce62267b701e7b9f'); c.start(); print(c.session.save())\"\n```\n\nসেটা এখানে paste করো!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]), parse_mode='Markdown')
    
    elif data == "menu_accounts":
        if not accounts:
            await query.edit_message_text("👥 **No accounts!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("➕ Add", callback_data="add_account_how")],[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
            return
        msg = f"👥 **Total: {len(accounts)}**\n\n"
        kb = []
        for i, acc in enumerate(accounts):
            s = "🟢" if acc.get('enabled', True) else "🔴"
            mode = "🤖" if acc.get('mode') == 'ai' else "📋"
            name = acc.get('name', f"User{acc['id']}")
            msg += f"{s} #{i+1} {name} [{mode}]\n"
            kb.append([InlineKeyboardButton(f"{'🔴' if acc.get('enabled', True) else '🟢'} Toggle #{i+1}", callback_data=f"tog_{i}")])
            kb.append([InlineKeyboardButton(f"🗑 Delete #{i+1}", callback_data=f"delacc_{i}")])
        kb.append([InlineKeyboardButton("➕ Add", callback_data="add_account_how")])
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("tog_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            accounts[idx]['enabled'] = not accounts[idx].get('enabled', True)
            _save_sessions()
        await button_callback(update, context)
    
    # ===== DELETE ACCOUNT =====
    elif data.startswith("delacc_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            acc = accounts[idx]
            kb = [
                [InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_del_{idx}")],
                [InlineKeyboardButton("❌ Cancel", callback_data="menu_accounts")]
            ]
            await query.edit_message_text(
                f"⚠️ **Confirm Delete** ⚠️\n\n"
                f"👤 **{acc.get('name', 'Unknown')}**\n"
                f"🆔 `{acc['id']}`\n\n"
                f"নিশ্চিত?",
                reply_markup=InlineKeyboardMarkup(kb),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Invalid account!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_accounts")]]))
    
    elif data.startswith("confirm_del_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(accounts):
            acc = accounts.pop(idx)
            try:
                await acc['client'].disconnect()
                logger.info(f"🔌 Disconnected client: {acc.get('name', 'Unknown')}")
            except Exception as e:
                logger.warning(f"Disconnect error: {e}")
            _save_sessions()
            logger.info(f"🗑 Account deleted: {acc.get('name', 'Unknown')} (ID: {acc['id']})")
            await query.edit_message_text(
                f"✅ **Account Deleted!** 🎉\n\n"
                f"👤 `{acc.get('name', 'Unknown')}`\n"
                f"🆔 `{acc['id']}`",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Accounts", callback_data="menu_accounts")]]),
                parse_mode='Markdown'
            )
        else:
            await query.edit_message_text("❌ Invalid index!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    # ===== WELCOME MENU =====
    elif data == "menu_welcome":
        welcome_msg = get_setting('welcome_message', 'Not set')
        welcome_img = get_setting('welcome_image', '')
        has_img = "✅" if (welcome_img and os.path.exists(welcome_img)) else "❌"
        
        msg = f"👋 **Welcome Settings**\n\n"
        msg += f"📝 Message: `{welcome_msg[:50]}...`\n"
        msg += f"🖼️ Image: {has_img}\n\n"
        msg += "ফার্স্ট মেসেজে ইউজারকে ওয়েলকাম মেসেজ + ফোটো দেখাবে!"
        
        kb = [
            [InlineKeyboardButton("✏️ Edit Welcome Text", callback_data="edit_welcome_text")],
            [InlineKeyboardButton("🖼️ Upload Welcome Image", callback_data="upload_welcome_image")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "edit_welcome_text":
        context.user_data['awaiting'] = 'welcome_text'
        current = get_setting('welcome_message', '')
        await query.edit_message_text(
            f"✏️ **Current Welcome Message:**\n\n{current}\n\n**নতুন Welcome Message পাঠাও:**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_welcome")]])
        )
    
    elif data == "upload_welcome_image":
        context.user_data['awaiting'] = 'welcome_image'
        await query.edit_message_text(
            "🖼️ **Welcome Image পাঠাও:**\n\nএটা প্রথম মেসেজে ফোটো হিসেবে যাবে।",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_welcome")]])
        )
    
    elif data == "menu_ai":
        ai_count = sum(1 for a in accounts if a.get('mode') == 'ai')
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        msg = f"🤖 **AI Mode**\n\nAI: {ai_count}/{len(accounts)}\nModel: `{model}`"
        kb = [
            [InlineKeyboardButton("🟢 Start AI", callback_data="ai_start")],
            [InlineKeyboardButton("🔴 Keyword Mode", callback_data="ai_stop")],
            [InlineKeyboardButton("⚡ Change Model", callback_data="change_model")],
            [InlineKeyboardButton("🔄 Reset Counters", callback_data="reset_counters")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "ai_start":
        for acc in accounts:
            acc['mode'] = 'ai'
        await query.edit_message_text("✅ **AI Mode Started!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]))
    
    elif data == "ai_stop":
        for acc in accounts:
            acc['mode'] = 'keyword'
        await query.edit_message_text("✅ **Keyword Mode!**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif data == "reset_counters":
        customer_message_count.clear()
        await query.edit_message_text("✅ Counters reset!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]))
    
    elif data == "change_model":
        kb = [
            [InlineKeyboardButton("🟢 GPT-4o Mini", callback_data="model_openai/gpt-4o-mini")],
            [InlineKeyboardButton("🔵 GPT-4o", callback_data="model_openai/gpt-4o")],
            [InlineKeyboardButton("🟣 Gemini 2.0 Flash", callback_data="model_google/gemini-2.0-flash-exp")],
            [InlineKeyboardButton("🟠 Llama 3.3 70B", callback_data="model_meta-llama/llama-3.3-70b-instruct")],
            [InlineKeyboardButton("🔙", callback_data="menu_ai")]
        ]
        await query.edit_message_text("⚡ **Select Model**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("model_"):
        model = data.replace("model_", "")
        set_setting('openrouter_model', model)
        await query.edit_message_text(f"✅ Model: `{model}`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]), parse_mode='Markdown')
    
    elif data == "menu_payment":
        upi = get_setting('upi_id', 'Not set')
        paytm = get_setting('paytm_num', 'Not set')
        has_qr = os.path.exists(get_setting('qr_code_path', '')) if get_setting('qr_code_path', '') else False
        msg = f"💰 **PAYMENT**\n\n📱 UPI: `{upi}`\n💳 PayTm: `{paytm}`\n🖼️ QR: {'✅' if has_qr else '❌'}"
        kb = [
            [InlineKeyboardButton("📱 Set UPI", callback_data="set_upi")],
            [InlineKeyboardButton("💳 Set PayTm", callback_data="set_paytm")],
            [InlineKeyboardButton("🖼️ Upload QR", callback_data="upload_qr")],
            [InlineKeyboardButton("💰 Edit Price", callback_data="edit_prices")],
            [InlineKeyboardButton("🖼️ Price Image", callback_data="upload_price_image")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "set_upi":
        context.user_data['awaiting'] = 'upi_id'
        await query.edit_message_text("📝 **UPI ID পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]))
    elif data == "set_paytm":
        context.user_data['awaiting'] = 'paytm_num'
        await query.edit_message_text("💳 **PayTm Number পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]))
    elif data == "upload_qr":
        context.user_data['awaiting'] = 'qr_code'
        await query.edit_message_text("🖼️ **QR Photo পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]))
    elif data == "edit_prices":
        context.user_data['awaiting'] = 'prices'
        current = get_setting('price_list_text', DEFAULT_PRICE_LIST)
        await query.edit_message_text(f"💰 **Current:**\n{current}\n\n**New price text পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]), parse_mode='Markdown')
    elif data == "upload_price_image":
        context.user_data['awaiting'] = 'price_image'
        await query.edit_message_text("🖼️ **Price list photo পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_payment")]]))
    
    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text("📭 No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
            return
        page = int(context.user_data.get('reply_page', 0))
        per_page = 5
        total = max(1, (len(replies) + per_page - 1) // per_page)
        start = page * per_page
        end = start + per_page
        page_list = replies[start:end]
        msg = f"📋 **Page {page+1}/{total}**\n\n"
        for r in page_list:
            rid, kw, rt, tp = r
            e = "🔑" if tp == "exact" else "🔍"
            msg += f"{e} ID:{rid} `{kw[:20]}`\n  ➜ {rt[:35]}...\n\n"
        kb = []
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️", callback_data=f"rp_{page-1}"))
        if page < total - 1:
            nav.append(InlineKeyboardButton("▶️", callback_data=f"rp_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("rp_"):
        context.user_data['reply_page'] = int(data.split("_")[1])
        await button_callback(update, context)
    
    elif data == "add_reply_keyword":
        context.user_data['awaiting'] = 'keyword'
        await query.edit_message_text("➕ **Keyword পাঠাও:**\n\nযেমন: `price`, `kaha karu`, `scan`", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif data == "reply_type_exact":
        context.user_data['reply_type'] = 'exact'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text("➕ **Reply text পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif data == "reply_type_contains":
        context.user_data['reply_type'] = 'contains'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text("➕ **Reply text পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif data == "menu_del_reply":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text("📭 No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
            return
        kb = [[InlineKeyboardButton(f"🗑 ID:{r[0]} {r[1][:15]}", callback_data=f"cd_{r[0]}")] for r in replies[:10]]
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text("🗑 **Select to delete:**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("cd_"):
        rid = int(data.split("_")[1])
        await query.edit_message_text(f"⚠️ Delete ID {rid}?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes", callback_data=f"dd_{rid}")],[InlineKeyboardButton("❌ No", callback_data="menu_del_reply")]]))
    
    elif data.startswith("dd_"):
        rid = int(data.split("_")[1])
        status = "✅ Deleted!" if delete_reply(rid) else "❌ Not found!"
        await query.edit_message_text(status, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
    elif data == "menu_settings":
        w = '✅' if get_setting('welcome_enabled','1')=='1' else '❌'
        bp = '✅' if get_setting('block_photo_enabled','1')=='1' else '❌'
        t = '✅' if get_setting('typing_enabled','1')=='1' else '❌'
        tt = int(get_setting('typing_duration','3'))
        dr = '✅' if get_setting('default_reply_enabled','0')=='1' else '❌'
        
        kb = [
            [InlineKeyboardButton(f"👋 Welcome {w}", callback_data="tw")],
            [InlineKeyboardButton(f"📸 Block Photo {bp}", callback_data="tbp")],
            [InlineKeyboardButton(f"⌨️ Typing {t} ({tt}s)", callback_data="stt")],
            [InlineKeyboardButton(f"💬 Default {dr}", callback_data="tdr")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text("⚙️ **Settings**", reply_markup=InlineKeyboardMarkup(kb))
    
    elif data == "tw":
        cur = get_setting('welcome_enabled','1')
        set_setting('welcome_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    elif data == "tbp":
        cur = get_setting('block_photo_enabled','1')
        set_setting('block_photo_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    elif data == "stt":
        kb = [
            [InlineKeyboardButton("⏱️ 2s", callback_data="tt_2"), InlineKeyboardButton("⏱️ 3s", callback_data="tt_3"), InlineKeyboardButton("⏱️ 5s", callback_data="tt_5")],
            [InlineKeyboardButton("⏱️ 7s", callback_data="tt_7"), InlineKeyboardButton("⏱️ 10s", callback_data="tt_10"), InlineKeyboardButton("⏱️ 15s", callback_data="tt_15")],
            [InlineKeyboardButton("🔙", callback_data="menu_settings")]
        ]
        await query.edit_message_text("⏱️ **Typing Duration**", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("tt_"):
        set_setting('typing_duration', data.split("_")[1])
        await query.edit_message_text(f"✅ Typing: {data.split('_')[1]}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_settings")]]))
    elif data == "tdr":
        cur = get_setting('default_reply_enabled','0')
        set_setting('default_reply_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    
    elif data == "menu_status":
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        ai_active = sum(1 for a in accounts if a.get('mode')=='ai')
        tt = int(get_setting('typing_duration','3'))
        typing_st = '✅ On' if get_setting('typing_enabled','1')=='1' else '❌ Off'
        bp_st = '✅ On' if get_setting('block_photo_enabled','1')=='1' else '❌ Off'
        
        accs = "\n".join([f"{'🟢' if a.get('enabled',True) else '🔴'} #{i+1} {a['name']} {'🤖' if a.get('mode')=='ai' else '📋'}" for i,a in enumerate(accounts)]) or "No accounts"
        msg = f"📊 **STATUS**\n\n"
        msg += f"👥 Accounts: {len(accounts)}\n{accs}\n\n"
        msg += f"🤖 AI Mode: {ai_active}/{len(accounts)}\n"
        msg += f"🧠 Model: `{model}`\n"
        msg += f"📝 Replies: {get_reply_count()}\n"
        msg += f"⌨️ Typing: {typing_st} | ⏱️ {tt}s\n"
        msg += f"📸 Block Photo: {bp_st}"
        
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]), parse_mode='Markdown')

# ===== ERROR HANDLER =====
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Bot error: {context.error}")

# ===== KEEP ALIVE =====
async def keep_accounts_alive():
    while True:
        try:
            for acc in accounts:
                try:
                    client = acc['client']
                    if not client.is_connected():
                        logger.warning(f"🔄 Reconnecting: {acc['name']}")
                        await client.connect()
                        if not await client.is_user_authorized():
                            await client.start()
                        logger.info(f"✅ Reconnected: {acc['name']}")
                except:
                    pass
            await asyncio.sleep(30)
        except:
            await asyncio.sleep(30)

# ===== BOT RUNNER =====
async def run_bot():
    init_db()
    logger.info("✅ Database ready")
    
    get_ai_bot()
    logger.info("✅ AI Bot initialized")
    
    await start_all_accounts()
    asyncio.create_task(keep_accounts_alive())
    logger.info("✅ Keep-alive started")
    
    for attempt in range(5):
        try:
            bot = Bot(token=BOT_TOKEN)
            webhook_info = await bot.get_webhook_info()
            if webhook_info.url:
                logger.info(f"⚠️ Webhook found: {webhook_info.url}, deleting...")
                await bot.delete_webhook(drop_pending_updates=True)
                await asyncio.sleep(3)
            
            await bot.delete_webhook(drop_pending_updates=True)
            await asyncio.sleep(2)
            
            try:
                await bot.get_updates(offset=-1, timeout=1, allowed_updates=[])
                await asyncio.sleep(1)
                await bot.get_updates(offset=-1, timeout=1, allowed_updates=[])
            except:
                pass
            
            await asyncio.sleep(2)
            logger.info(f"✅ Cleanup {attempt+1}/5")
            break
        except Conflict as e:
            logger.warning(f"⚠️ Conflict {attempt+1}: {e}")
            if attempt < 4:
                await asyncio.sleep((attempt + 1) * 5)
        except Exception as e:
            logger.warning(f"⚠️ Cleanup {attempt+1}: {e}")
            await asyncio.sleep(5)
    
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )
    
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    await app.initialize()
    await app.start()
    
    for poll_attempt in range(3):
        try:
            await app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=["message", "callback_query"],
                poll_interval=0.5
            )
            logger.info("✅ Bot polling started!")
            break
        except Conflict as e:
            logger.error(f"❌ Polling conflict {poll_attempt+1}: {e}")
            if poll_attempt < 2:
                await asyncio.sleep(10)
            else:
                raise
    
    try:
        await asyncio.Event().wait()
    finally:
        try:
            await app.updater.stop()
        except:
            pass
        try:
            await app.stop()
        except:
            pass
        try:
            await app.shutdown()
        except:
            pass

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, use_reloader=False)

def run_main():
    try:
        current_pid = os.getpid()
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        killed = 0
        for line in result.stdout.split('\n'):
            if 'python' in line and 'main.py' in line:
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pid = int(parts[1])
                        if pid != current_pid:
                            os.kill(pid, signal.SIGKILL)
                            killed += 1
                    except:
                        pass
        
        result2 = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        for line in result2.stdout.split('\n'):
            if 'getUpdates' in line or 'telegram' in line.lower():
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pid = int(parts[1])
                        if pid != current_pid:
                            os.kill(pid, signal.SIGKILL)
                            killed += 1
                    except:
                        pass
        
        if killed > 0:
            logger.info(f"🔪 Killed {killed} old instance(s)")
            sleep(5)
    except Exception as e:
        logger.warning(f"Kill error: {e}")
    
    try:
        if os.path.exists("bot.pid"):
            os.remove("bot.pid")
    except:
        pass
    
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))
    
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask started")
    sleep(3)
    
    try:
        asyncio.run(run_bot())
    except Exception as e:
        logger.error(f"❌ Bot error: {e}", exc_info=True)
    finally:
        try:
            if os.path.exists("bot.pid"):
                os.remove("bot.pid")
        except:
            pass

if __name__ == "__main__":
    run_main()
