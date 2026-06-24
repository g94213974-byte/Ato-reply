import asyncio
import os
import json
import logging
import random
import signal
import subprocess
import time
import re
import sys
from threading import Thread
from time import sleep

from flask import Flask, jsonify, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import Application, ApplicationBuilder, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import Conflict

from telethon import TelegramClient, events, errors
from telethon import TelegramClient, events, errors
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import BlockRequest, DeleteContactsRequest
from telethon.tl.functions.messages import ReadHistoryRequest
from telethon.errors import PhoneNumberAppSignupForbiddenError, PhoneCodeInvalidError, PhoneCodeExpiredError, SessionPasswordNeededError, UserRestrictedError, FloodWaitError

from database import init_db, get_setting, set_setting, add_reply, delete_reply, get_all_replies, get_reply_count, add_user_reply, get_user_specific_replies, delete_user_reply, get_all_user_replies, get_user_reply_count
from config import BOT_TOKEN, ADMIN_ID, ACCOUNTS, API_ID, API_HASH

from shruti_bot import ShrutiAIBot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

# ===== GLOBAL =====
accounts = []
customer_count = {}
customer_payment_photos = {}
_processing = set()
SESSION_FILE = "saved_sessions.json"
_bot_started = False
LOCK_FILE = "bot_instance.lock"
RESTRICTED_ACCOUNTS_FILE = "restricted_accounts.json"

# Login state tracking
_login_sessions = {}

# Webhook URL
RENDER_URL = os.environ.get('RENDER_EXTERNAL_URL', '')
WEBHOOK_URL = f"{RENDER_URL}/webhook" if RENDER_URL else ""

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
                    'rupees', 'rs', '.', 'dham', 'send karo', 'money', 'paise', 'payment method',
                    'payment kaise', 'kaha karu']

PHOTO_BLOCK_KEYWORDS = ['pic', 'pics', 'picture', 'photo', 'image', 'nude pic', 'nude photo',
                        'naked', 'xxx pic', 'sexy pic', 'dikhao', 'show', 'full nude',
                        'nangi', 'boob', 'boobs', 'dikha', 'mms', 'xnxx', 'xxx',
                        'nude video', 'sex video', 'blue film', 'bf', 'xxx video']

shruti_bot = None
application = None
_loop = None


def get_ai_bot():
    global shruti_bot
    if shruti_bot is None:
        try:
            shruti_bot = ShrutiAIBot()
            logger.info("AI Bot initialized")
        except Exception as e:
            logger.error(f"AI bot init error: {e}")
    return shruti_bot


def _save_sessions():
    sessions = [acc['session'] for acc in accounts if 'session' in acc and acc['session']]
    try:
        with open(SESSION_FILE, 'w') as f:
            json.dump(sessions, f, indent=2)
    except:
        pass


def _load_sessions():
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return []


def _save_restricted():
    restricted = []
    for acc in accounts:
        if acc.get('restricted', False):
            restricted.append({'id': acc['id'], 'name': acc.get('name', '')})
    try:
        with open(RESTRICTED_ACCOUNTS_FILE, 'w') as f:
            json.dump(restricted, f, indent=2)
    except:
        pass


# ===== LOGIN WITH PHONE + OTP + 2FA =====
async def login_with_phone(phone_number, temp_key):
    try:
        client = TelegramClient(StringSession(), API_ID, API_HASH, sequential_updates=True)
        await client.connect()

        if not await client.is_user_authorized():
            try:
                sent = await client.send_code_request(phone_number)
                phone_code_hash = sent.phone_code_hash

                _login_sessions[temp_key] = {
                    'phone': phone_number,
                    'client': client,
                    'step': 'otp',
                    'phone_code_hash': phone_code_hash,
                    'created_at': time.time()
                }

                return {"status": "otp_sent", "message": f"OTP sent to {phone_number}"}
            except FloodWaitError as e:
                return {"status": "flood", "message": f"Flood wait: {e.seconds}s", "wait": e.seconds}
            except Exception as e:
                await client.disconnect()
                return {"status": "error", "message": str(e)}
        else:
            me = await client.get_me()
            _login_sessions[temp_key] = {
                'phone': phone_number,
                'client': client,
                'step': 'completed',
                'session': client.session.save()
            }
            return {"status": "already_logged", "session": client.session.save(), "user": me.first_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def verify_otp(temp_key, otp_code):
    if temp_key not in _login_sessions:
        return {"status": "error", "message": "Session expired. Start again."}

    session_data = _login_sessions[temp_key]
    client = session_data['client']

    if session_data['step'] != 'otp':
        return {"status": "error", "message": "Wrong step. Expected OTP verification."}

    try:
        await client.sign_in(
            phone=session_data['phone'],
            code=otp_code,
            phone_code_hash=session_data['phone_code_hash']
        )

        me = await client.get_me()
        session_string = client.session.save()

        session_data['step'] = 'completed'
        session_data['session'] = session_string
        session_data['user'] = me.first_name

        await client.disconnect()

        return {
            "status": "success",
            "session": session_string,
            "user": {
                "id": me.id,
                "name": me.first_name,
                "username": me.username
            }
        }

    except SessionPasswordNeededError:
        session_data['step'] = '2fa'
        return {"status": "2fa_required", "message": "2FA password required"}
    except PhoneCodeInvalidError:
        return {"status": "error", "message": "Invalid OTP code"}
    except PhoneCodeExpiredError:
        return {"status": "error", "message": "OTP expired. Request a new one."}
    except UserRestrictedError:
        return {"status": "restricted", "message": "This account is restricted/banned"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def verify_2fa(temp_key, password):
    if temp_key not in _login_sessions:
        return {"status": "error", "message": "Session expired. Start again."}

    session_data = _login_sessions[temp_key]
    client = session_data['client']

    if session_data['step'] != '2fa':
        return {"status": "error", "message": "Wrong step. Expected 2FA."}

    try:
        await client.sign_in(password=password)

        me = await client.get_me()
        session_string = client.session.save()

        session_data['step'] = 'completed'
        session_data['session'] = session_string
        session_data['user'] = me.first_name

        await client.disconnect()

        return {
            "status": "success",
            "session": session_string,
            "user": {
                "id": me.id,
                "name": me.first_name,
                "username": me.username
            }
        }
    except SessionPasswordNeededError:
        return {"status": "error", "message": "Wrong 2FA password"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def start_single_account(session_string):
    try:
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH, sequential_updates=True)
        await client.start()
        me = await client.get_me()

        is_restricted = False
        try:
            await client.send_message(me.id, "✅")
            async for msg in client.iter_messages(me.id, limit=1):
                await client.delete_messages(me.id, [msg.id])
        except (UserRestrictedError, errors.UserRestrictedError) as e:
            is_restricted = True
            logger.warning(f"Account {me.first_name} (ID: {me.id}) is RESTRICTED!")
        except FloodWaitError as e:
            logger.warning(f"Flood wait on {me.first_name}: {e.seconds}s")
        except Exception as e:
            logger.warning(f"Account check error for {me.first_name}: {e}")

        acc_info = {
            'id': me.id,
            'name': me.first_name or f"User{me.id}",
            'client': client,
            'enabled': not is_restricted,
            'mode': 'ai',
            'session': session_string,
            'restricted': is_restricted
        }

        if is_restricted:
            logger.info(f"Restricted account added but DISABLED: {me.first_name}")
            try:
                await client.log_out()
                logger.info(f"Logged out restricted account: {me.first_name}")
            except:
                pass
        else:
            accounts.append(acc_info)
            _register_handler(client, acc_info)
            _save_sessions()
            logger.info(f"Connected: {me.first_name} (ID: {me.id})")

        _save_restricted()
        return acc_info
    except UserRestrictedError as e:
        logger.error(f"Account is restricted/banned: {e}")
        return {"error": "restricted", "message": "Account is restricted/banned"}
    except Exception as e:
        logger.error(f"Account failed: {e}")
        return None


async def start_all_accounts():
    saved = _load_sessions()
    if saved:
        for s in saved:
            try:
                await start_single_account(s)
                await asyncio.sleep(2)
            except:
                pass
    logger.info(f"{len(accounts)} accounts connected (restricted excluded)")


# ===== RESTRICTED ACCOUNT CHECKING =====
async def check_account_restrictions():
    while True:
        await asyncio.sleep(60)
        for i, acc in enumerate(accounts[:]):
            if acc.get('restricted', False):
                continue
            try:
                c = acc['client']
                me = await c.get_me()
                try:
                    await c.send_message(me.id, ".")
                    async for msg in c.iter_messages(me.id, limit=1):
                        await c.delete_messages(me.id, [msg.id])
                except (UserRestrictedError, errors.UserRestrictedError):
                    logger.warning(f"Account {acc['name']} became restricted! Removing...")
                    acc['restricted'] = True
                    acc['enabled'] = False
                    try:
                        await c.log_out()
                    except:
                        pass
                    try:
                        await c.disconnect()
                    except:
                        pass
                    accounts.remove(acc)
                    _save_sessions()
                    _save_restricted()
                    await admin_broadcast(f"Account Restricted!\n\n{acc['name']}\nID: {acc['id']}\n\nAccount removed and logged out.")
            except:
                pass


async def admin_broadcast(text):
    for acc in accounts:
        if acc.get('enabled', True) and not acc.get('restricted', False):
            try:
                await acc['client'].send_message(ADMIN_ID, text)
                break
            except:
                pass


def _register_handler(client, acc_info):
    @client.on(events.NewMessage(incoming=True))
    async def handler(event):
        try:
            if not event.is_private:
                return
            sender = await event.get_sender()
            if not sender:
                return
            uid = sender.id
            if uid == ADMIN_ID:
                return
            if not acc_info.get('enabled', True):
                return
            if acc_info.get('restricted', False):
                return
            if uid in _processing:
                return
            _processing.add(uid)
            try:
                await process_message(event, client, acc_info, uid)
            finally:
                _processing.discard(uid)
        except Exception as e:
            logger.error(f"Handler error: {e}")
            _processing.discard(uid)


async def process_message(event, client, acc_info, uid):
    chat_id = event.chat_id
    msg_text = event.message.text or ""

    if uid not in customer_count:
        customer_count[uid] = 0
    prev = customer_count[uid]

    if event.message.sticker:
        logger.info(f"Sticker from {uid}")
        await do_typing(client, chat_id)
        await send_welcome(client, chat_id)
        customer_count[uid] = prev + 1
        return

    if event.message.photo or (event.message.document and event.message.document.mime_type and 'image' in event.message.document.mime_type):
        block = get_setting('block_photo_enabled', '1') == '1'
        if block:
            await handle_photo_block(event, client, uid)
        else:
            await handle_payment_screenshot(event, client, uid)
        return

    if not msg_text.strip():
        return

    if prev == 0:
        logger.info(f"First message from {uid} - welcome only")
        await do_typing(client, chat_id)
        await send_welcome(client, chat_id)
        customer_count[uid] = 1
        return

    try:
        peer = await event.get_input_chat()
        await client(ReadHistoryRequest(peer=peer, max_id=event.message.id))
    except:
        pass

    msg_lower = msg_text.lower().strip()

    # Check global replies
    replies = get_all_replies()
    for rid, keyword, reply_text, rtype in replies:
        kw = keyword.lower().strip()
        if rtype == "exact" and msg_lower == kw:
            await do_typing(client, chat_id)
            await event.respond(reply_text)
            customer_count[uid] = prev + 1
            return
        elif rtype == "contains" and kw in msg_lower:
            await do_typing(client, chat_id)
            await event.respond(reply_text)
            customer_count[uid] = prev + 1
            return

    # Check user-specific replies
    user_replies = get_user_specific_replies(uid)
    for reply_id, user_id, keyword, reply_text, rtype in user_replies:
        kw = keyword.lower().strip()
        if rtype == "exact" and msg_lower == kw:
            await do_typing(client, chat_id)
            await event.respond(reply_text)
            customer_count[uid] = prev + 1
            return
        elif rtype == "contains" and kw in msg_lower:
            await do_typing(client, chat_id)
            await event.respond(reply_text)
            customer_count[uid] = prev + 1
            return

    if any(kw in msg_lower for kw in PAYMENT_KEYWORDS + ['kaha kar', 'kisme kar', 'kaise kar', 'kaha pay', 'kaise pay', 'kaha bhej', 'kaise bhej', 'method', 'scan', 'qr', 'upi id', 'kya hai', 'kaha hai']):
        await do_typing(client, chat_id)
        await send_payment_info(client, chat_id, event)
        customer_count[uid] = prev + 1
        return

    if any(kw in msg_lower for kw in PHOTO_BLOCK_KEYWORDS):
        await do_typing(client, chat_id)
        await event.respond("Payment karo baby, phir maza lo Service ready hai!")
        customer_count[uid] = prev + 1
        return

    if any(kw in msg_lower for kw in SERVICE_KEYWORDS):
        await do_typing(client, chat_id)
        price_text = get_setting('price_list_text', DEFAULT_PRICE_LIST)
        price_img = get_setting('price_list_image', '')
        if price_img and os.path.exists(price_img):
            await client.send_file(chat_id, price_img, caption=price_text)
        else:
            await event.respond(price_text)
        await asyncio.sleep(0.5)
        await event.respond(random.choice([
            "Bolo kitna time chahiye? 10 min ya 20 min?",
            "Pay karo baby, ready hoon main!",
            "Payment karo, phir maza lo!"
        ]))
        customer_count[uid] = prev + 1
        return

    if any(kw in msg_lower for kw in ['real', 'meet', 'mil', 'aao', 'aana', 'ghar', 'location', 'aaja', 'offline', 'milna', 'live']):
        await do_typing(client, chat_id)
        await event.respond("Only online service baby Payment karo, ready hoon!")
        customer_count[uid] = prev + 1
        return

    await do_typing(client, chat_id)
    try:
        ai = get_ai_bot()
        reply = None
        if ai:
            reply = ai.get_reply(uid, msg_text, prev)
        if not reply:
            reply = get_default_reply(msg_lower)
    except:
        reply = get_default_reply(msg_lower)
    if reply:
        await event.respond(reply)
    customer_count[uid] = prev + 1


def get_default_reply(msg_lower):
    if any(w in msg_lower for w in ['hi', 'hello', 'hey', 'hii', 'hy', 'hlo', 'helo']):
        return random.choice([
            "Haan baby, ready hoon! Kitna time chahiye?",
            "Hmm baby, kya chahiye?",
            "Hi baby, ready hoon main! Batao kya lena hai?"
        ])
    return random.choice([
        "Ready hoon baby, payment karo, maza lo!",
        "Main ready hoon, tum payment karo!",
        "Service ready hai baby, payment karo!",
        "Batao kitna minute chahiye, payment karo!",
        "Ready baby! Payment karo, phir maza lo!"
    ])


async def do_typing(client, chat_id):
    try:
        if get_setting('typing_enabled', '1') == '0':
            await asyncio.sleep(0.3)
            return
        dur = int(get_setting('typing_duration', '3'))
        async with client.action(chat_id, "typing"):
            await asyncio.sleep(dur)
    except:
        await asyncio.sleep(0.3)


async def send_welcome(client, chat_id):
    try:
        welcome_text = get_setting('welcome_message', '')
        welcome_img = get_setting('welcome_image', '')
        if not welcome_text:
            welcome_text = "SHRUTI PRICE LIST\n\n10 MIN VC = 99\n20 MIN VC = 119\nDEMO (2 MIN FULL NUDE) = 49\n\nPay karo baby, phir maza lo!"
        if welcome_img and os.path.exists(welcome_img):
            try:
                await client.send_file(chat_id, welcome_img, caption=welcome_text)
                return
            except:
                pass
        await client.send_message(chat_id, welcome_text)
    except Exception as e:
        logger.error(f"Welcome error: {e}")


async def send_payment_info(client, chat_id, event=None):
    try:
        upi = get_setting('upi_id', '')
        paytm = get_setting('paytm_num', '')
        qr = get_setting('qr_code_path', '')
        msg = "Payment Details\n\n"
        if upi:
            msg += f"UPI ID: {upi}\n"
        if paytm:
            msg += f"PayTm: {paytm}\n"
        msg += "\nScan karo baby, payment karo!"
        if qr and os.path.exists(qr):
            try:
                await client.send_file(chat_id, qr, caption=msg)
                return
            except:
                pass
        await event.respond(msg)
    except Exception as e:
        logger.error(f"Payment info error: {e}")


async def handle_photo_block(event, client, uid):
    try:
        peer = await event.get_input_chat()
        try:
            await client.delete_messages(peer, [event.message.id], revoke=True)
        except:
            pass
        try:
            async for msg in client.iter_messages(peer, limit=100):
                try:
                    await client.delete_messages(peer, [msg.id], revoke=True)
                except:
                    pass
        except:
            pass
        try:
            await client.delete_dialog(peer)
        except:
            pass
        await asyncio.sleep(1)
        try:
            await client(BlockRequest(id=uid))
        except:
            pass
        try:
            await client(DeleteContactsRequest(id=[uid]))
        except:
            pass
        logger.info(f"Photo block done for {uid}")
    except Exception as e:
        logger.error(f"Photo block error: {e}")


async def handle_payment_screenshot(event, client, uid):
    try:
        if event.message.photo:
            photo = event.message.photo[-1]
        elif event.message.document:
            photo = event.message.document
        else:
            return
        os.makedirs('payment_screenshots', exist_ok=True)
        path = f"payment_screenshots/{uid}_{event.message.id}.jpg"
        await photo.download_async(path)
        customer_payment_photos[uid] = path
        name = event.sender.first_name if event.sender else "Unknown"
        await event.respond("Payment screenshot received baby!\n\nMain abhi ADMIN ko forward kar rahi hoon...\nAdmin aapko 2 minute mein personally handle karega!\n\nPlease wait baby...")
        await client.send_message(ADMIN_ID, f"NEW PAYMENT!\n\nCustomer: {name}\nID: {uid}\nMessages: {customer_count.get(uid, 0)}\n\nADMIN CHECK!")
        await client.send_file(ADMIN_ID, path)
        customer_count[uid] = -2
    except Exception as e:
        logger.error(f"Screenshot error: {e}")


# ===== BOT STUFF =====
async def show_main_menu(update, context):
    connected = len([a for a in accounts if a.get('enabled', True) and not a.get('restricted', False)])
    restricted = len([a for a in accounts if a.get('restricted', False)])
    model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
    keyboard = [
        [InlineKeyboardButton("Login with Phone", callback_data="menu_login")],
        [InlineKeyboardButton("AI Mode", callback_data="menu_ai")],
        [InlineKeyboardButton("Payment", callback_data="menu_payment")],
        [InlineKeyboardButton("Welcome", callback_data="menu_welcome")],
        [InlineKeyboardButton("Replies", callback_data="menu_replies")],
        [InlineKeyboardButton("Add Reply", callback_data="add_reply_keyword")],
        [InlineKeyboardButton("Batch Add Replies", callback_data="batch_add_replies")],
        [InlineKeyboardButton("User-Specific Reply", callback_data="menu_user_reply")],
        [InlineKeyboardButton("Delete Reply", callback_data="menu_del_reply")],
        [InlineKeyboardButton("Accounts", callback_data="menu_accounts")],
        [InlineKeyboardButton("Add Account (String)", callback_data="add_account_how")],
        [InlineKeyboardButton("Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("Status", callback_data="menu_status")],
    ]
    text = f"Shruti's Panel\n\nActive: {connected} | Restricted: {restricted}\nModel: {model}\n\nSelect:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def msg_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    user_data = context.user_data
    awaiting = user_data.get('awaiting', '')
    if awaiting:
        if update.message.text:
            await handle_text_input(update, context)
        elif update.message.photo:
            await handle_photo_input(update, context)
        elif update.message.contact:
            await handle_contact_input(update, context)
        return
    text = update.message.text or ""
    if len(text) > 100:
        await add_account(update, context, text)
        return
    await show_main_menu(update, context)


async def add_account(update, context, session):
    msg = await update.message.reply_text("Adding...")
    try:
        acc = await start_single_account(session)
        if acc and 'error' not in acc:
            await msg.edit_text(f"Added!\n{acc['name']}\nID: {acc['id']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
        elif acc and acc.get('error') == 'restricted':
            await msg.edit_text("Account is RESTRICTED/Banned!\n\nAuto-logged out and disabled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
        else:
            await msg.edit_text("Failed!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
    except Exception as e:
        await msg.edit_text(f"Failed: {str(e)[:200]}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))


async def handle_text_input(update, context):
    text = update.message.text.strip()
    awaiting = context.user_data.get('awaiting', '')
    back = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]])

    if awaiting.startswith('login_phone_'):
        temp_key = awaiting.replace('login_phone_', '')
        result = await login_with_phone(text, temp_key)
        if result['status'] == 'otp_sent':
            context.user_data['awaiting'] = f'login_otp_{temp_key}'
            await update.message.reply_text(f"OTP sent to {text}\n\nEnter OTP code:", reply_markup=back)
        elif result['status'] == 'flood':
            await update.message.reply_text(f"Flood wait: {result.get('wait', '?')}s\n\nTry again later.", reply_markup=back)
        elif result['status'] == 'already_logged':
            session = result['session']
            acc = await start_single_account(session)
            context.user_data['awaiting'] = ''
            await update.message.reply_text(f"Already logged in as {result['user']}\n\nAccount added!", reply_markup=back)
        else:
            await update.message.reply_text(f"Error: {result['message']}", reply_markup=back)

    elif awaiting.startswith('login_otp_'):
        temp_key = awaiting.replace('login_otp_', '')
        otp = text.strip()
        result = await verify_otp(temp_key, otp)
        if result['status'] == 'success':
            session = result['session']
            context.user_data['awaiting'] = ''
            await update.message.reply_text(f"Login Successful!\n{result['user']['name']}\n\nAdding account...", reply_markup=back)
            acc = await start_single_account(session)
            if acc and 'error' not in acc:
                await update.message.reply_text(f"Account added: {acc['name']}", reply_markup=back)
            else:
                await update.message.reply_text("Account may be restricted. Check accounts menu.", reply_markup=back)
        elif result['status'] == '2fa_required':
            context.user_data['awaiting'] = f'login_2fa_{temp_key}'
            await update.message.reply_text(f"2FA Password Required!\n\nEnter your 2FA password:", reply_markup=back)
        elif result['status'] == 'restricted':
            await update.message.reply_text(f"Account is RESTRICTED!\n\nCannot add this account.", reply_markup=back)
        else:
            await update.message.reply_text(f"Error: {result['message']}", reply_markup=back)

    elif awaiting.startswith('login_2fa_'):
        temp_key = awaiting.replace('login_2fa_', '')
        password = text.strip()
        result = await verify_2fa(temp_key, password)
        if result['status'] == 'success':
            session = result['session']
            context.user_data['awaiting'] = ''
            await update.message.reply_text(f"2FA Verified!\n{result['user']['name']}\n\nAdding account...", reply_markup=back)
            acc = await start_single_account(session)
            await update.message.reply_text(f"Account added: {acc.get('name', '?')}", reply_markup=back)
        else:
            await update.message.reply_text(f"Error: {result['message']}", reply_markup=back)

    elif awaiting == 'upi_id':
        set_setting('upi_id', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"UPI: {text}", reply_markup=back)
    elif awaiting == 'paytm_num':
        set_setting('paytm_num', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"PayTm: {text}", reply_markup=back)
    elif awaiting == 'prices':
        set_setting('price_list_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("Price list updated!", reply_markup=back)
    elif awaiting == 'welcome_text':
        set_setting('welcome_message', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("Welcome message updated!", reply_markup=back)
    elif awaiting == 'keyword':
        context.user_data['add_keyword'] = text
        context.user_data['awaiting'] = 'reply_type'
        kb = [[InlineKeyboardButton("Exact", callback_data="reply_type_exact")], [InlineKeyboardButton("Contains", callback_data="reply_type_contains")], [InlineKeyboardButton("Cancel", callback_data="main_menu")]]
        await update.message.reply_text(f"Keyword: {text}\n\nMatch type:", reply_markup=InlineKeyboardMarkup(kb))
    elif awaiting == 'reply_text':
        kw = context.user_data.get('add_keyword', '')
        tp = context.user_data.get('reply_type', 'exact')
        rid = add_reply(kw, text, tp)
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"Reply added! (ID: {rid})", reply_markup=back)
    elif awaiting == 'batch_replies':
        lines = text.strip().split('\n')
        added = 0
        errors = []
        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            parts = line.split('|')
            if len(parts) < 2:
                errors.append(f"Line {i+1}: Invalid format (need keyword|reply)")
                continue
            kw = parts[0].strip()
            reply = parts[1].strip()
            rtype = 'contains'
            if len(parts) >= 3:
                rtype = parts[2].strip().lower()
                if rtype not in ['exact', 'contains']:
                    rtype = 'contains'
            if kw and reply:
                rid = add_reply(kw, reply, rtype)
                added += 1
        context.user_data['awaiting'] = ''
        msg_txt = f"Batch Add Complete!\n\nAdded: {added}"
        if errors:
            msg_txt += f"\nErrors: {len(errors)}\n" + "\n".join(errors[:5])
        await update.message.reply_text(msg_txt, reply_markup=back)
    elif awaiting == 'default_reply_text':
        set_setting('default_reply_text', text)
        context.user_data['awaiting'] = ''
        await update.message.reply_text("Default reply updated!", reply_markup=back)
    elif awaiting == 'user_reply_keyword':
        context.user_data['user_reply_keyword'] = text
        context.user_data['awaiting'] = 'user_reply_userid'
        await update.message.reply_text(f"Keyword: {text}\n\nNow enter the User ID for whom this reply should work:", reply_markup=back)
    elif awaiting == 'user_reply_userid':
        try:
            user_id = int(text.strip())
            context.user_data['user_reply_userid'] = user_id
            context.user_data['awaiting'] = 'user_reply_text'
            await update.message.reply_text(f"User ID: {user_id}\n\nNow send the reply text:", reply_markup=back)
        except:
            await update.message.reply_text("Invalid User ID. Send a numeric ID.", reply_markup=back)
    elif awaiting == 'user_reply_text':
        kw = context.user_data.get('user_reply_keyword', '')
        uid = context.user_data.get('user_reply_userid', 0)
        reply_text = text
        rid = add_user_reply(uid, kw, reply_text, 'exact')
        context.user_data['awaiting'] = ''
        await update.message.reply_text(f"User-Specific Reply Added!\n\nUser: {uid}\nKeyword: {kw}\nReply ID: {rid}\n\nNote: This reply will only work for this specific user!", reply_markup=back)


async def handle_contact_input(update, context):
    awaiting = context.user_data.get('awaiting', '')
    if awaiting == 'contact_login':
        contact = update.message.contact
        if contact:
            phone = contact.phone_number
            if not phone.startswith('+'):
                phone = '+' + phone
            temp_key = str(int(time.time()))
            context.user_data['awaiting'] = f'login_phone_{temp_key}'
            context.user_data['temp_key'] = temp_key
            result = await login_with_phone(phone, temp_key)
            if result['status'] == 'otp_sent':
                context.user_data['awaiting'] = f'login_otp_{temp_key}'
                await update.message.reply_text(f"OTP sent to {phone}\n\nEnter OTP code:")
            else:
                context.user_data['awaiting'] = ''
                await update.message.reply_text(f"Error: {result.get('message', 'Login failed')}")


async def handle_photo_input(update, context):
    awaiting = context.user_data.get('awaiting', '')
    photo = update.message.photo[-1]
    file = await photo.get_file()
    if awaiting == 'qr_code':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/qr_code.jpg")
        set_setting('qr_code_path', "payment_assets/qr_code.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("QR saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
    elif awaiting == 'price_image':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/price_list.jpg")
        set_setting('price_list_image', "payment_assets/price_list.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("Price list image saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
    elif awaiting == 'welcome_image':
        os.makedirs('payment_assets', exist_ok=True)
        await file.download_to_drive("payment_assets/welcome_image.jpg")
        set_setting('welcome_image', "payment_assets/welcome_image.jpg")
        context.user_data['awaiting'] = ''
        await update.message.reply_text("Welcome image saved!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))


async def button_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await show_main_menu(update, context)
        return

    elif data == "menu_login":
        kb = [
            [InlineKeyboardButton("Send Phone Number", callback_data="login_send_phone")],
            [InlineKeyboardButton("Share Contact", callback_data="login_share_contact")],
            [InlineKeyboardButton("Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "Login with Phone Number\n\n"
            "Option 1: Type your phone number (e.g., +91XXXXXXXXXX)\n"
            "Option 2: Share your contact via Telegram\n\n"
            "After OTP, you may need 2FA password if enabled.",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "login_send_phone":
        temp_key = str(int(time.time()))
        context.user_data['awaiting'] = f'login_phone_{temp_key}'
        context.user_data['temp_key'] = temp_key
        await query.edit_message_text(
            "Send your phone number\n\n"
            "Format: +91XXXXXXXXXX\n\n"
            "Type the number with country code:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Cancel", callback_data="main_menu")]])
        )

    elif data == "login_share_contact":
        context.user_data['awaiting'] = 'contact_login'
        await query.edit_message_text(
            "Share your contact\n\n"
            "Use the contact share button below to send your phone number:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Share Contact", callback_data="share_contact_btn")],
                [InlineKeyboardButton("Cancel", callback_data="main_menu")]
            ])
        )

    elif data == "add_account_how":
        await query.edit_message_text(
            "Add Account Methods\n\n"
            "Method 1: Phone Login (New)\n"
            "Use the login button from main menu.\n\n"
            "Method 2: String Session\n"
            "Run this command locally:\n\n"
            "pip install telethon && python -c \"from telethon.sync import TelegramClient; from telethon.sessions import StringSession; c = TelegramClient(StringSession(), 37362415, '88f99afa3b9a81adce62267b701e7b9f'); c.start(); print(c.session.save())\"\n\n"
            "Paste the string here to add!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]])
        )

    elif data == "menu_accounts":
        active = [a for a in accounts if a.get('enabled', True) and not a.get('restricted', False)]
        restricted = [a for a in accounts if a.get('restricted', False)]
        if not accounts:
            await query.edit_message_text("No accounts!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Login with Phone", callback_data="menu_login")],[InlineKeyboardButton("Add String", callback_data="add_account_how")],[InlineKeyboardButton("Back", callback_data="main_menu")]]))
            return
        msg = f"Total: {len(accounts)}\nActive: {len(active)}\nRestricted: {len(restricted)}\n\n"
        kb = []
        for i, acc in enumerate(accounts):
            is_restricted = acc.get('restricted', False)
            s = "R" if is_restricted else ("A" if acc.get('enabled', True) else "D")
            mode = "AI" if acc.get('mode') == 'ai' else "KW"
            name = acc.get('name', f"User{acc['id']}")
            status = " [RESTRICTED]" if is_restricted else ""
            msg += f"{s} #{i+1} {name} [{mode}]{status}\n"
            if not is_restricted:
                kb.append([InlineKeyboardButton(f"{'Disable' if acc.get('enabled', True) else 'Enable'} #{i+1}", callback_data=f"tog_{i}")])
            kb.append([InlineKeyboardButton(f"Delete #{i+1}", callback_data=f"delacc_{i}")])
        kb.append([InlineKeyboardButton("Login with Phone", callback_data="menu_login")])
        kb.append([InlineKeyboardButton("Add String", callback_data="add_account_how")])
        kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("tog_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts) and not accounts[idx].get('restricted', False):
            accounts[idx]['enabled'] = not accounts[idx].get('enabled', True)
            _save_sessions()
        await button_callback(update, context)

    elif data.startswith("delacc_"):
        idx = int(data.split("_")[1])
        if 0 <= idx < len(accounts):
            acc = accounts[idx]
            kb = [[InlineKeyboardButton("Yes, Delete", callback_data=f"confirm_del_{idx}")],[InlineKeyboardButton("Cancel", callback_data="menu_accounts")]]
            await query.edit_message_text(f"Confirm Delete\n\n{acc.get('name', 'Unknown')}\nID: {acc['id']}\n{'RESTRICTED' if acc.get('restricted') else 'Active'}\n\nSure?", reply_markup=InlineKeyboardMarkup(kb))
        else:
            await query.edit_message_text("Invalid account!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_accounts")]]))

    elif data.startswith("confirm_del_"):
        idx = int(data.split("_")[2])
        if 0 <= idx < len(accounts):
            acc = accounts.pop(idx)
            try:
                await acc['client'].disconnect()
            except:
                pass
            _save_sessions()
            _save_restricted()
            await query.edit_message_text(f"Account Deleted!\n\n{acc.get('name', 'Unknown')}\nID: {acc['id']}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Accounts", callback_data="menu_accounts")]]))
        else:
            await query.edit_message_text("Invalid index!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "menu_welcome":
        welcome_msg = get_setting('welcome_message', '')
        if not welcome_msg:
            welcome_msg = "Not set (default will be used)"
        welcome_img = get_setting('welcome_image', '')
        has_img = "Yes" if (welcome_img and os.path.exists(welcome_img)) else "No"
        msg = f"Welcome Settings\n\nMessage: {welcome_msg[:60]}...\nImage: {has_img}\n\nFirst message = welcome only!"
        kb = [[InlineKeyboardButton("Edit Welcome Text", callback_data="edit_welcome_text")],[InlineKeyboardButton("Upload Welcome Image", callback_data="upload_welcome_image")],[InlineKeyboardButton("Back", callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "edit_welcome_text":
        context.user_data['awaiting'] = 'welcome_text'
        current = get_setting('welcome_message', '(Default)')
        await query.edit_message_text(f"Current Welcome Message:\n\n{current}\n\nSend new Welcome Message:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_welcome")]]))

    elif data == "upload_welcome_image":
        context.user_data['awaiting'] = 'welcome_image'
        await query.edit_message_text("Send Welcome Image:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_welcome")]]))

    elif data == "menu_ai":
        ai_count = sum(1 for a in accounts if a.get('mode') == 'ai' and not a.get('restricted', False))
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        msg = f"AI Mode\n\nAI Active: {ai_count}/{len([a for a in accounts if not a.get('restricted')])}\nModel: {model}"
        kb = [[InlineKeyboardButton("Start AI", callback_data="ai_start")],[InlineKeyboardButton("Keyword Mode", callback_data="ai_stop")],[InlineKeyboardButton("Change Model", callback_data="change_model")],[InlineKeyboardButton("Reset Counters", callback_data="reset_counters")],[InlineKeyboardButton("Back", callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "ai_start":
        for acc in accounts:
            if not acc.get('restricted', False):
                acc['mode'] = 'ai'
        await query.edit_message_text("AI Mode Started!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_ai")]]))

    elif data == "ai_stop":
        for acc in accounts:
            if not acc.get('restricted', False):
                acc['mode'] = 'keyword'
        await query.edit_message_text("Keyword Mode!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "reset_counters":
        customer_count.clear()
        _processing.clear()
        await query.edit_message_text("Counters reset!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_ai")]]))

    elif data == "change_model":
        kb = [[InlineKeyboardButton("GPT-4o Mini", callback_data="model_openai/gpt-4o-mini")],[InlineKeyboardButton("GPT-4o", callback_data="model_openai/gpt-4o")],[InlineKeyboardButton("Gemini 2.0 Flash", callback_data="model_google/gemini-2.0-flash-exp")],[InlineKeyboardButton("Llama 3.3 70B", callback_data="model_meta-llama/llama-3.3-70b-instruct")],[InlineKeyboardButton("Back", callback_data="menu_ai")]]
        await query.edit_message_text("Select Model", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("model_"):
        model = data.replace("model_", "")
        set_setting('openrouter_model', model)
        await query.edit_message_text(f"Model: {model}", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_ai")]]))

    elif data == "menu_payment":
        upi = get_setting('upi_id', 'Not set')
        paytm = get_setting('paytm_num', 'Not set')
        qr_path = get_setting('qr_code_path', '')
        has_qr = os.path.exists(qr_path) if qr_path else False
        msg = f"PAYMENT\n\nUPI: {upi}\nPayTm: {paytm}\nQR: {'Yes' if has_qr else 'No'}"
        kb = [[InlineKeyboardButton("Set UPI", callback_data="set_upi")],[InlineKeyboardButton("Set PayTm", callback_data="set_paytm")],[InlineKeyboardButton("Upload QR", callback_data="upload_qr")],[InlineKeyboardButton("Edit Price", callback_data="edit_prices")],[InlineKeyboardButton("Price Image", callback_data="upload_price_image")],[InlineKeyboardButton("Back", callback_data="main_menu")]]
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif data == "set_upi":
        context.user_data['awaiting'] = 'upi_id'
        await query.edit_message_text("Send UPI ID:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_payment")]]))

    elif data == "set_paytm":
        context.user_data['awaiting'] = 'paytm_num'
        await query.edit_message_text("Send PayTm Number:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_payment")]]))

    elif data == "upload_qr":
        context.user_data['awaiting'] = 'qr_code'
        await query.edit_message_text("Send QR Photo:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_payment")]]))

    elif data == "edit_prices":
        context.user_data['awaiting'] = 'prices'
        current = get_setting('price_list_text', DEFAULT_PRICE_LIST)
        await query.edit_message_text(f"Current:\n{current}\n\nSend new price text:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_payment")]]))

    elif data == "upload_price_image":
        context.user_data['awaiting'] = 'price_image'
        await query.edit_message_text("Send Price list photo:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_payment")]]))

    elif data == "menu_replies":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text("No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
            return
        page = int(context.user_data.get('reply_page', 0))
        per_page = 5
        total = max(1, (len(replies) + per_page - 1) // per_page)
        start = page * per_page
        end = start + per_page
        page_list = replies[start:end]
        msg = f"Page {page+1}/{total}\n\n"
        for r in page_list:
            rid, kw, rt, tp = r
            e = "Exact" if tp == "exact" else "Contains"
            msg += f"ID:{rid} {kw[:20]}\n  -> {rt[:35]}... ({e})\n\n"
        kb = []
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("Prev", callback_data=f"rp_{page-1}"))
        if page < total - 1:
            nav.append(InlineKeyboardButton("Next", callback_data=f"rp_{page+1}"))
        if nav:
            kb.append(nav)
        kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("rp_"):
        context.user_data['reply_page'] = int(data.split("_")[1])
        await button_callback(update, context)

    elif data == "add_reply_keyword":
        context.user_data['awaiting'] = 'keyword'
        await query.edit_message_text("Send keyword:\n\nExample: price, kaha karu, scan", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "reply_type_exact":
        context.user_data['reply_type'] = 'exact'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text("Send reply text:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "reply_type_contains":
        context.user_data['reply_type'] = 'contains'
        context.user_data['awaiting'] = 'reply_text'
        await query.edit_message_text("Send reply text:", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "batch_add_replies":
        context.user_data['awaiting'] = 'batch_replies'
        await query.edit_message_text(
            "Batch Add Replies\n\n"
            "Format per line:\n"
            "keyword | reply text | match_type\n\n"
            "Match type: exact or contains (default: contains)\n\n"
            "Example:\n"
            "price | 99 for 10 min | exact\n"
            "scan | Scan karo baby | contains\n"
            "hello | Hi baby, kya chahiye? | exact\n\n"
            "Send all lines at once!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]])
        )

    elif data == "menu_user_reply":
        kb = [
            [InlineKeyboardButton("Add User-Specific Reply", callback_data="add_user_reply")],
            [InlineKeyboardButton("List User Replies", callback_data="list_user_replies")],
            [InlineKeyboardButton("Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "User-Specific Replies\n\n"
            "You can add replies that ONLY work for specific users.\n"
            "Other users won't trigger these replies.\n\n"
            "Useful for giving different responses to different customers!",
            reply_markup=InlineKeyboardMarkup(kb)
        )

    elif data == "add_user_reply":
        context.user_data['awaiting'] = 'user_reply_keyword'
        await query.edit_message_text(
            "Add User-Specific Reply\n\n"
            "Enter the keyword that should trigger the reply:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_user_reply")]])
        )

    elif data == "list_user_replies":
        user_replies = get_all_user_replies()
        if not user_replies:
            await query.edit_message_text("No user-specific replies!\n\nAdd one from the menu.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_user_reply")]]))
            return
        msg = "User-Specific Replies\n\n"
        kb = []
        for rid, uid, kw, rt, tp in user_replies[:20]:
            msg += f"ID:{rid} | User:{uid} | {kw[:15]}\n  -> {rt[:30]}...\n\n"
            kb.append([InlineKeyboardButton(f"Delete ID:{rid} (User:{uid})", callback_data=f"del_user_reply_{rid}")])
        kb.append([InlineKeyboardButton("Back", callback_data="menu_user_reply")])
        await query.edit_message_text(msg[:4000], reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("del_user_reply_"):
        rid = int(data.split("_")[3])
        kb = [[InlineKeyboardButton("Yes", callback_data=f"confirm_del_user_{rid}")],[InlineKeyboardButton("No", callback_data="list_user_replies")]]
        await query.edit_message_text(f"Delete user reply ID {rid}?", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("confirm_del_user_"):
        rid = int(data.split("_")[3])
        result = delete_user_reply(rid)
        await query.edit_message_text("Deleted!" if result else "Not found!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_user_reply")]]))

    elif data == "menu_del_reply":
        replies = get_all_replies()
        if not replies:
            await query.edit_message_text("No replies!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))
            return
        kb = [[InlineKeyboardButton(f"ID:{r[0]} {r[1][:15]}", callback_data=f"cd_{r[0]}")] for r in replies[:10]]
        kb.append([InlineKeyboardButton("Back", callback_data="main_menu")])
        await query.edit_message_text("Select to delete:", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("cd_"):
        rid = int(data.split("_")[1])
        await query.edit_message_text(f"Delete ID {rid}?", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data=f"dd_{rid}")],[InlineKeyboardButton("No", callback_data="menu_del_reply")]]))

    elif data.startswith("dd_"):
        rid = int(data.split("_")[1])
        status = "Deleted!" if delete_reply(rid) else "Not found!"
        await query.edit_message_text(status, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))

    elif data == "menu_settings":
        w = 'On' if get_setting('welcome_enabled','1')=='1' else 'Off'
        bp = 'On' if get_setting('block_photo_enabled','1')=='1' else 'Off'
        t = 'On' if get_setting('typing_enabled','1')=='1' else 'Off'
        tt = int(get_setting('typing_duration','3'))
        dr = 'On' if get_setting('default_reply_enabled','0')=='1' else 'Off'
        kb = [[InlineKeyboardButton(f"Welcome {w}", callback_data="tw")],[InlineKeyboardButton(f"Block Photo {bp}", callback_data="tbp")],[InlineKeyboardButton(f"Typing {t} ({tt}s)", callback_data="stt")],[InlineKeyboardButton(f"Default {dr}", callback_data="tdr")],[InlineKeyboardButton("Back", callback_data="main_menu")]]
        await query.edit_message_text("Settings", reply_markup=InlineKeyboardMarkup(kb))

    elif data == "tw":
        cur = get_setting('welcome_enabled','1')
        set_setting('welcome_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "tbp":
        cur = get_setting('block_photo_enabled','1')
        set_setting('block_photo_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "stt":
        kb = [[InlineKeyboardButton("2s", callback_data="tt_2"), InlineKeyboardButton("3s", callback_data="tt_3"), InlineKeyboardButton("5s", callback_data="tt_5")],[InlineKeyboardButton("7s", callback_data="tt_7"), InlineKeyboardButton("10s", callback_data="tt_10"), InlineKeyboardButton("15s", callback_data="tt_15")],[InlineKeyboardButton("Back", callback_data="menu_settings")]]
        await query.edit_message_text("Typing Duration", reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("tt_"):
        set_setting('typing_duration', data.split("_")[1])
        await query.edit_message_text(f"Typing: {data.split('_')[1]}s", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu_settings")]]))

    elif data == "tdr":
        cur = get_setting('default_reply_enabled','0')
        set_setting('default_reply_enabled', '0' if cur=='1' else '1')
        await button_callback(update, context)

    elif data == "menu_status":
        active = [a for a in accounts if a.get('enabled', True) and not a.get('restricted', False)]
        restricted = [a for a in accounts if a.get('restricted', False)]
        model = get_setting('openrouter_model', 'openai/gpt-4o-mini')
        ai_active = sum(1 for a in active if a.get('mode')=='ai')
        tt = int(get_setting('typing_duration','3'))
        typing_st = 'On' if get_setting('typing_enabled','1')=='1' else 'Off'
        bp_st = 'On' if get_setting('block_photo_enabled','1')=='1' else 'Off'

        accs = "\n".join([f"{'A' if a.get('enabled',True) else 'D'} #{i+1} {a['name']} {'AI' if a.get('mode')=='ai' else 'KW'} {'R' if a.get('restricted') else ''}" for i,a in enumerate(accounts)]) or "No accounts"

        msg = f"STATUS\n\n"
        msg += f"Total: {len(accounts)} | Active: {len(active)} | Restricted: {len(restricted)}\n"
        msg += f"{accs}\n\n"
        msg += f"AI Mode: {ai_active}/{len(active)}\n"
        msg += f"Model: {model}\n"
        msg += f"Global Replies: {get_reply_count()}\n"
        msg += f"User Replies: {get_user_reply_count()}\n"
        msg += f"Total Chats: {len(customer_count)}\n"
        msg += f"Typing: {typing_st} | {tt}s\n"
        msg += f"Block Photo: {bp_st}"

        await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="main_menu")]]))


# ===== WEBHOOK & FLASK =====
@flask_app.route('/webhook', methods=['POST'])
def webhook_handler():
    global application, _loop

    if application is None or _loop is None:
        logger.error("Application not ready yet!")
        return "Bot not ready", 503

    try:
        data = request.get_json(force=True)
        update = Update.de_json(data, application.bot)

        future = asyncio.run_coroutine_threadsafe(
            application.process_update(update),
            _loop
        )
        try:
            future.result(timeout=5)
        except Exception as e:
            logger.warning(f"Process update timeout/warning: {e}")

        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return f"Error: {str(e)}", 500


@flask_app.route('/')
def home():
    return jsonify({"status": "running", "bot": "Shruti AI Bot", "accounts": len(accounts)})


@flask_app.route('/health')
def health():
    return jsonify({"status": "ok"}), 200


@flask_app.route('/setwebhook', methods=['GET'])
def set_webhook_route():
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
    resp = requests.post(url, json={
        "url": WEBHOOK_URL,
        "drop_pending_updates": True,
        "max_connections": 1,
        "allowed_updates": ["message", "callback_query"]
    })
    return jsonify(resp.json())


@flask_app.route('/delwebhook', methods=['GET'])
def del_webhook_route():
    import requests
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
    resp = requests.post(url, json={"drop_pending_updates": True})
    return jsonify(resp.json())


async def setup_webhook():
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
            json={"drop_pending_updates": True}
        )
        await asyncio.sleep(2)

        resp = await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
            json={
                "url": WEBHOOK_URL,
                "drop_pending_updates": True,
                "max_connections": 1,
                "allowed_updates": ["message", "callback_query"]
            }
        )
        data = resp.json()
        logger.info(f"Webhook setup: {data}")
        return data.get("ok", False)


async def run_bot():
    global _bot_started, application, _loop
    
    logger.info("=" * 50)
    logger.info("BOT STARTING...")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {sys.platform}")
    logger.info("=" * 50)
    
    _loop = asyncio.get_event_loop()
    # ... বাকি কোড)
    
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, 'r') as f:
                old_pid = f.read().strip()
            if old_pid and old_pid.isdigit():
                try:
                    os.kill(int(old_pid), 0)
                    logger.warning(f"Another instance (PID {old_pid}) running! Exiting.")
                    return
                except ProcessLookupError:
                    pass
        except:
            pass
    
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))
    
    if _bot_started:
        logger.warning("Bot already started! Skipping...")
        return
    _bot_started = True
    
    init_db()
    logger.info("Database ready")
    get_ai_bot()
    
    webhook_ok = await setup_webhook()
    if not webhook_ok:
        logger.error("Failed to set webhook!")
    
    await start_all_accounts()
    asyncio.create_task(keep_alive())
    asyncio.create_task(check_account_restrictions())
    
    application = (ApplicationBuilder()
           .token(BOT_TOKEN)
           .build())
    
    application.add_handler(MessageHandler(filters.ALL, msg_handler))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)
    
    await application.initialize()
    await application.start()
    
    logger.info(f"Bot running on webhook mode!")
    logger.info(f"Webhook URL: {WEBHOOK_URL}")
    
    try:
        await asyncio.Event().wait()
    finally:
        try:
            await application.stop()
        except:
            pass
        try:
            await application.shutdown()
        except:
            pass
        _bot_started = False
        try:
            os.remove(LOCK_FILE)
        except:
            pass


async def error_handler(update, context):
    logger.error(f"Bot error: {context.error}")


async def keep_alive():
    while True:
        try:
            for acc in accounts:
                try:
                    c = acc['client']
                    if not c.is_connected():
                        await c.connect()
                        if not await c.is_user_authorized():
                            await c.start()
                except:
                    pass
            await asyncio.sleep(30)
        except:
            await asyncio.sleep(30)


def run_flask():
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False, use_reloader=False)


def run_main():
    global _bot_started
    
    if _bot_started:
        return
    
    pid = os.getpid()
    logger.info(f"Starting PID: {pid}")
    
    try:
        os.remove("bot.pid")
    except:
        pass
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))
    
    Thread(target=run_flask, daemon=True).start()
    sleep(3)
    
    try:
        asyncio.run(run_bot())
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
    finally:
        try:
            os.remove("bot.pid")
        except:
            pass
        _bot_started = False
        try:
            os.remove(LOCK_FILE)
        except:
            pass


def start_bot_async():
    """Run the bot in a background thread with its own event loop."""
    global _bot_started
    if _bot_started:
        return
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(run_bot())
    except Exception as e:
        logger.error(f"Bot thread error: {e}", exc_info=True)
    finally:
        loop.close()
        _bot_started = False


def run_flask_with_bot():
    """Initialize DB, start bot thread, then run Flask."""
    global _bot_started
    
    init_db()
    logger.info("Database initialized")
    get_ai_bot()
    
    # Start bot in background thread
    bot_thread = Thread(target=start_bot_async, daemon=True)
    bot_thread.start()
    sleep(5)  # Give bot time to start
    
    # Run Flask (blocking)
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False, use_reloader=False)


if __name__ == "__main__":
    if "worker" in sys.argv:
        run_main()
    else:
        run_flask_with_bot()
