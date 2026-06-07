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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes

from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest
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

DEFAULT_PRICE_LIST = """💕 **SHRUTI'S PRICE LIST** 💕

📱 10 MIN VIDEO CALL → ₹49 🔥
📱 20 MIN VIDEO CALL → ₹59 💋
🎬 DEMO SHOW → ₹19 ONLY 😘
**💰 HOW TO PAY 💰**
Check my profile for payment details
Then send me the SCREENSHOT here baby!"""

# Shruti AI bot instance
shruti_bot = None

def get_ai_bot():
    global shruti_bot
    if shruti_bot is None:
        try:
            shruti_bot = ShrutiAIBot()
            logger.info("✅ Shruti AI Bot initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to init AI bot: {e}")
    return shruti_bot

# ===== AI FAIL HOLE SHUDHU SIMPLE REPLY =====
def get_minimal_fallback(msg_text):
    """Only used when AI completely fails - simple, no flirty pre-built"""
    simple_replies = [
        "Haan baby, kya bolna chahte ho?",
        "Baby, thoda clearly batao na.",
        "Kya chahiye aapko? Batao na.",
        "Baby, aap kya bolna chahte ho?"
    ]
    return random.choice(simple_replies)

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

# ===== AI MODE - ONLY CUSTOM REPLIES + AI =====
async def handle_ai_mode(event, client, acc_info, sender_id):
    try:
        msg_text = event.message.text or ""
        chat_id = event.chat_id
        
        if not msg_text.strip():
            return
        
        # Photo handle
        if event.message.photo:
            await handle_payment_screenshot(event, client, sender_id)
            return
        
        # Track message count
        if sender_id not in customer_message_count:
            customer_message_count[sender_id] = 0
        count = customer_message_count[sender_id]
        
        # Mark as read
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
        except:
            pass
        
        # Natural delay
        await asyncio.sleep(random.uniform(0.5, 1.5))
        
        async with client.action(chat_id, "typing"):
            msg_lower = msg_text.lower().strip()
            replies = get_all_replies()
            matched = False
            reply = None
            
            # ===== STEP 1: ONLY USER-ADDED CUSTOM REPLIES =====
            for rid, keyword, reply_text, rtype in replies:
                kw = keyword.lower().strip()
                if rtype == "exact" and msg_lower == kw:
                    reply = reply_text
                    matched = True
                    logger.info(f"✅ Custom exact match: {kw}")
                    break
                elif rtype == "contains" and kw in msg_lower:
                    reply = reply_text
                    matched = True
                    logger.info(f"✅ Custom contains match: {kw}")
                    break
            
            # ===== STEP 2: AI REPLY (ONLY if NO custom match) =====
            if not matched:
                logger.info(f"🤖 AI replying to: {msg_text[:50]}...")
                try:
                    ai_bot = get_ai_bot()
                    if ai_bot:
                        reply = ai_bot.get_reply(sender_id, msg_text, count)
                    else:
                        reply = get_minimal_fallback(msg_text)
                    
                    # AI fail check
                    if not reply or len(reply.strip()) < 2:
                        logger.warning("⚠️ AI returned empty, using minimal fallback...")
                        reply = get_minimal_fallback(msg_text)
                    else:
                        # AI success - typing delay
                        typing_time = min(len(reply) * 0.02, 2.0)
                        await asyncio.sleep(typing_time)
                    
                except Exception as ai_err:
                    logger.error(f"❌ AI error: {ai_err}")
                    reply = get_minimal_fallback(msg_text)
            
            # ===== STEP 3: SEND REPLY =====
            await event.respond(reply)
            
            # Price list on 3rd message
            if count == 2:
                await asyncio.sleep(0.5)
                try:
                    price_text = get_setting('price_list_text', DEFAULT_PRICE_LIST)
                    price_image = get_setting('price_list_image', '')
                    if price_image and os.path.exists(price_image):
                        await client.send_file(chat_id, price_image, caption=price_text)
                    else:
                        await event.respond(price_text)
                except Exception as e:
                    logger.error(f"Price list error: {e}")
            
            customer_message_count[sender_id] = count + 1
    
    except Exception as e:
        logger.error(f"AI mode error: {e}")
        try:
            await event.respond(get_minimal_fallback(""))
        except:
            pass

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
            f"💬 Messages: {customer_message_count.get(sender_id, 0)}\n\n"
            f"🔴 **ADMIN PLEASE CHECK!** 🔴",
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
        if not msg_text:
            return
        
        chat_id = event.chat_id
        sender = await event.get_sender()
        sender_id = sender.id
        
        # Photo block check
        if event.message.photo or (event.message.media and isinstance(event.message.media, MessageMediaPhoto)):
            if get_setting('block_photo_enabled', '1') == '1':
                try:
                    await client(BlockRequest(id=sender_id))
                    peer = await event.get_input_chat()
                    await client.delete_messages(peer, [event.message.id], revoke=True)
                except:
                    pass
            return
        
        try:
            peer = await event.get_input_chat()
            await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
        except:
            pass
        
        typing_enabled = get_setting('typing_enabled', '1') == '1'
        typing_duration = int(get_setting('typing_duration', '3'))
        msg_lower = msg_text.lower().strip()
        replies = get_all_replies()
        matched = False
        
        for rid, keyword, reply_text, rtype in replies:
            kw = keyword.lower().strip()
            if rtype == "exact" and msg_lower == kw:
                matched = True
                if typing_enabled:
                    async with client.action(chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                await event.respond(reply_text)
                break
            elif rtype == "contains" and kw in msg_lower:
                matched = True
                if typing_enabled:
                    async with client.action(chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                await event.respond(reply_text)
                break
        
        if not matched:
            if get_setting('default_reply_enabled', '0') == '1':
                if typing_enabled:
                    async with client.action(chat_id, "typing"):
                        await asyncio.sleep(typing_duration)
                default_reply = get_setting('default_reply_text', 'Hi baby')
                await event.respond(default_reply)
    except Exception as e:
        logger.error(f"Keyword mode error: {e}")

# ===== ADMIN BOT HANDLERS =====
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    connected = len(accounts)
    model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
    
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
    text += f"🧠 AI Model: {model}\n\n"
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
    msg = await update.message.reply_text("⏳ **Account adding...**")
    try:
        acc_info = await start_single_account(session_string)
        await msg.edit_text(f"✅ **Account Added!** 🎉\n👤 {acc_info['name']}\n🆔 `{acc_info['id']}`\n📊 Total: {len(accounts)}",
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
    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("✅ Welcome text updated!", reply_markup=kb_back)
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
            kb.append([InlineKeyboardButton(f"{'🔴' if acc.get('enabled', True) else '🟢'} #{i+1}", callback_data=f"tog_{i}")])
        kb.append([InlineKeyboardButton("➕ Add", callback_data="add_account_how")])
        kb.append([InlineKeyboardButton("🔙", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))
    
    elif data.startswith("tog_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            accounts[idx]['enabled'] = not accounts[idx].get('enabled', True)
            _save_sessions()
        await button_callback(update, context)
    
    elif data == "menu_ai":
        ai_count = sum(1 for a in accounts if a.get('mode') == 'ai')
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        msg = f"🤖 **AI Mode Control**\n\nAI Mode: {ai_count}/{len(accounts)}\nModel: `{model}`\n\nCustom Reply → AI"
        kb = [
            [InlineKeyboardButton("🟢 Start AI Mode", callback_data="ai_start")],
            [InlineKeyboardButton("🔴 Keyword Mode", callback_data="ai_stop")],
            [InlineKeyboardButton("⚡ Change Model", callback_data="change_model")],
            [InlineKeyboardButton("🔄 Reset Counters", callback_data="reset_counters")],
            [InlineKeyboardButton("🔙", callback_data="main_menu")]
        ]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb), parse_mode='Markdown')
    
    elif data == "ai_start":
        for acc in accounts:
            acc['mode'] = 'ai'
        await query.edit_message_text("✅ **AI Mode Started!** 🥰\n\nCustom Reply → AI",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="menu_ai")]]))
    
    elif data == "ai_stop":
        for acc in accounts:
            acc['mode'] = 'keyword'
        await query.edit_message_text("✅ **Keyword Mode!**",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
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
        await query.edit_message_text("➕ **Keyword পাঠাও:**", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙", callback_data="main_menu")]]))
    
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
            [InlineKeyboardButton(f"⌨️ Typing {t}", callback_data="tty")],
            [InlineKeyboardButton(f"⏱️ {tt}s", callback_data="stt")],
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
    elif data == "tty":
        cur = get_setting('typing_enabled','1')
        set_setting('typing_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    elif data == "stt":
        kb = [[InlineKeyboardButton("3s", callback_data="tt_3"), InlineKeyboardButton("5s", callback_data="tt_5"), InlineKeyboardButton("10s", callback_data="tt_10")],[InlineKeyboardButton("🔙", callback_data="menu_settings")]]
        await query.edit_message_text("⏱️ **Select typing duration:**", reply_markup=InlineKeyboardMarkup(kb))
    elif data.startswith("tt_"):
        set_setting('typing_duration', data.split("_")[1])
        await button_callback(update, context)
    elif data == "tdr":
        cur = get_setting('default_reply_enabled','0')
        set_setting('default_reply_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)
    
    elif data == "menu_status":
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        ai_active = sum(1 for a in accounts if a.get('mode')=='ai')
        accs = "\n".join([f"{'🟢' if a.get('enabled',True) else '🔴'} #{i+1} {a['name']} {'🤖' if a.get('mode')=='ai' else '📋'}" for i,a in enumerate(accounts)]) or "No accounts"
        msg = f"📊 **STATUS**\n\n👥 Accounts: {len(accounts)}\n{accs}\n\n🤖 AI Mode: {ai_active}/{len(accounts)}\n🧠 Model: `{model}`\n📝 Replies: {get_reply_count()}"
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
    
    # Initialize AI bot
    get_ai_bot()
    logger.info("✅ AI Bot initialized")
    
    await start_all_accounts()
    
    # Start keep-alive
    asyncio.create_task(keep_accounts_alive())
    logger.info("✅ Keep-alive started")
    
    # ===== CONFLICT FIX: Force clear all updates =====
    from telegram import Bot
    bot = Bot(token=BOT_TOKEN)
    
    for attempt in range(3):
        try:
            await bot.delete_webhook(drop_pending_updates=True)
            await asyncio.sleep(2)
            updates = await bot.get_updates(offset=-1, timeout=5)
            logger.info(f"✅ Webhook deleted and updates cleared (attempt {attempt+1})")
            break
        except Exception as e:
            logger.warning(f"⚠️ Cleanup attempt {attempt+1}: {e}")
            await asyncio.sleep(3)
    
    # Setup bot with ApplicationBuilder
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .get_updates_read_timeout(30)
        .build()
    )
    
    app.add_handler(MessageHandler(filters.ALL, message_handler))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_error_handler(error_handler)
    
    await app.initialize()
    await app.start()
    
    # Start polling
    try:
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=["message", "callback_query"],
            poll_interval=0.5,
            timeout=30
        )
        logger.info("✅ Bot polling started successfully!")
    except Exception as e:
        logger.error(f"❌ Polling start error: {e}")
        await asyncio.sleep(3)
        try:
            await app.updater.start_polling(drop_pending_updates=True)
            logger.info("✅ Bot polling started on retry!")
        except Exception as e2:
            logger.error(f"❌ Polling retry failed: {e2}")
    
    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False, use_reloader=False)

def run_main():
    # ===== FORCE KILL OLD INSTANCES =====
    try:
        current_pid = os.getpid()
        result = subprocess.run(["ps", "aux"], capture_output=True, text=True)
        for line in result.stdout.split('\n'):
            if 'python' in line and 'main.py' in line:
                parts = line.split()
                if len(parts) > 1:
                    try:
                        pid = int(parts[1])
                        if pid != current_pid:
                            os.kill(pid, signal.SIGKILL)
                            logger.warning(f"🔪 Killed old process: {pid}")
                    except (ValueError, ProcessLookupError):
                        pass
        sleep(3)
    except Exception as e:
        logger.warning(f"Kill old instances error: {e}")
    
    # PID file
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))
    
    # Flask thread
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    logger.info("✅ Flask started")
    sleep(2)
    
    # Run bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by keyboard")
    except Exception as e:
        logger.error(f"❌ Bot error: {e}", exc_info=True)
    finally:
        if os.path.exists("bot.pid"):
            os.remove("bot.pid")

if __name__ == "__main__":
    run_main()
