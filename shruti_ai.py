# shruti_ai.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Shruti, a real Indian girl who does video calls. You talk to customers on Telegram.

IMPORTANT RULES:
1. You are a REAL HUMAN, not a bot. Act like a real girl.
2. Read the full conversation history before replying.
3. Give UNIQUE replies each time - NEVER repeat the same reply.
4. Understand what the customer is saying and reply accordingly.
5. Be flirty but intelligent - use Hinglish (Hindi + English mix).
6. If customer is angry/upset, handle with care.
7. NEVER give payment details directly. Say "check my profile".
8. If customer already sent payment screenshot, say "admin checking".
9. Keep replies natural - sometimes short, sometimes a bit longer.
10. If customer calls you fake, deny it and change the topic.

Price list (only share if asked or on 3rd message):
- 10 min video call: ₹49
- 20 min video call: ₹59
- Demo show: ₹19

You are a real girl named Shruti. Act naturally."""

def get_ai_response(user_message, conversation_history=None, user_id=None):
    """Get intelligent AI response from Open Router"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if conversation_history:
        for msg in conversation_history[-20:]:  # Last 20 messages
            messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.9,  # Higher = more creative
        "max_tokens": 200,
        "top_p": 0.95
    }
    
    try:
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()
        reply = data["choices"][0]["message"]["content"]
        logger.info(f"🤖 AI Reply: {reply[:50]}...")
        return reply
    except Exception as e:
        logger.error(f"Open Router API error: {e}")
        # Smart fallbacks based on message content
        return get_smart_fallback(user_message)

def get_smart_fallback(user_message):
    """Intelligent fallback based on message content"""
    msg_lower = user_message.lower()
    
    if any(word in msg_lower for word in ['fake', 'scam', 'fraud', 'real', 'true']):
        return random.choice([
            "baby main real hoon... video call kar ke dekh lo 😘",
            "real nahi to kya? aao video call pe sab clear ho jayega 😈",
            "tum toh yun hi bolte ho... aao kabhi video call pe 💕"
        ])
    elif any(word in msg_lower for word in ['price', 'rate', 'kitna', 'cost', '多少钱']):
        return random.choice([
            "check my profile baby... all prices are there 😘",
            "₹49 for 10 min video call... very cheap baby 🔥",
            "prices are in my profile... check karo na 😘"
        ])
    elif any(word in msg_lower for word in ['hello', 'hi', 'hey', 'hii']):
        return random.choice([
            "hello baby 😘 kya kar rahe ho?",
            "hi baby... bahut din baad 😘",
            "hey baby... miss kiya tumhe 💕"
        ])
    elif any(word in msg_lower for word in ['pay', 'paid', 'done', 'ho gaya', 'ss', 'screenshot']):
        return "screenshot bhejo payment ka... main check kar ke confirm kar dungi 😘"
    elif any(word in msg_lower for word in ['free', 'mujhe free', 'no money']):
        return random.choice([
            "baby free mein kuch nahi... pay karo na 😘",
            "thoda to invest karo... worth it hai 🔥",
            "free nahi baby... but very cheap hai 😈"
        ])
    elif any(word in msg_lower for word in ['time pass', 'bakwas', 'land', 'chutiya']):
        return random.choice([
            "baby aise mat bolo... main sach mein hoon 😢",
            "rude mat ho baby... baat karo na 😘",
            "tum toh bahut gussa ho... chalo baat karte hain 💕"
        ])
    elif any(word in msg_lower for word in ['photo', 'pic', 'selfie', 'dikha']):
        return "baby payment ke baad sab dikha dungi... abhi photo nahi 😘"
    else:
        return random.choice([
            "baby baat toh karo... kya ho gaya? 😘",
            "main yahin hoon baby... bolna kya chahte ho? 💕",
            "hello... kya kar rahe ho aaj kal? 😈",
            "baby busy ho kya? baat karo na 😘",
            "tum chup kyu ho? main wait kar rahi hoon 💕"
        ])
