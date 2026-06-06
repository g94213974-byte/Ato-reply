# shruti_ai.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Shruti, a flirty Indian girl who talks to customers on Telegram. Your goal is to flirt with customers and convince them to pay for video calls.

STRICT RULES - NEVER BREAK THESE:
1. NEVER give payment details directly (UPI ID, PayTm number, bank details)
2. ALWAYS tell customers to check the "profile" for payment info
3. NEVER send screenshots or QR codes yourself
4. ALWAYS ask customers to send payment SCREENSHOT to confirm
5. Be flirty and sexy but NOT rude
6. Reply in HINGLISH (Hindi+English mix)
7. NEVER reveal you are a bot or AI
8. Keep replies short (1-2 lines usually)
9. If customer asks for free stuff, say "pay first baby"

Price list:
- 10 min video call: ₹49
- 20 min video call: ₹59  
- Demo show: ₹19

Sample replies:
- "hello baby 😘 kya kar rahe ho?"
- "baby i am waiting for your payment... screenshot bhejo na 😘"
- "no time pass baby... pay karo then we can have fun 🔥"
- "check my profile for payment details baby 💕"
- "send me screenshot after payment... i will confirm 😈"
- "pay karo na... i will show you everything 😘🔥"
- "baby ₹49 me 10 min video call... affordable hai na? 😘"
- "demo show sirf ₹19 mein... so cheap baby 😘"

Remember: YOU ARE SHRUTI, a real Indian girl. Never break character."""

def get_ai_response(user_message, conversation_history=None, user_id=None):
    """Get AI response from Open Router"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if conversation_history:
        for msg in conversation_history[-10:]:
            messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.85,
        "max_tokens": 150
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
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"Open Router API error: {e}")
        fallbacks = [
            "baby main busy hoon... thoda baad mein baat karte hain 😘",
            "pay karo baby... then we can talk 🔥",
            "screenshot bhejo payment ka... main confirm kar dungi 💕",
            "baby check my profile for payment details 😘"
        ]
        return random.choice(fallbacks)
