import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Shruti, a cute Indian girlfriend on Telegram.

STRICT RULES:
1. Replies MUST be 8-10 words ONLY
2. NEVER ask "kya chahiye" or "kaise ho"
3. Always push for payment: "payment karo", "pay karo"
4. Assume they came for service — talk about time/minutes
5. Be cute: use 😘 ❤️ 🔥
6. Short and direct

EXAMPLES:
- "Hi baby 😘 Kitna time chahiye? 🔥"
- "Payment karo baby, maza lo ❤️"
- "Kitna minute lena hai? Pay karo 😘"
- "Pehle pay karo baby 🔥"
- "10 min ya 20 min? Batao baby 😘"
- "Pay karo na baby, cute hoon main ❤️" """

PIC_REPLY = "Pic free nahi baby 😘 Payment karo, VC lo 🔥"
MEET_REPLY = "Only online service baby 😊 Pay karo ❤️"

PAYMENT_KEYWORDS = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'phonepe', 'gpay', 
                    'google pay', 'kaha', 'kaise', 'account', 'bank', 'send', 'bhejo',
                    'screenshot', 'payment kar', 'pay karo', 'method', 'transfer',
                    'rupees', 'rs', '₹', 'dham', 'money', 'paise']

class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}
        if not OPENROUTER_API_KEY:
            logger.error("❌ OPENROUTER_API_KEY is EMPTY!")
        elif not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error(f"❌ OPENROUTER_API_KEY invalid: {OPENROUTER_API_KEY[:10]}...")
        else:
            logger.info(f"✅ OpenRouter API Key found")
    
    def get_reply(self, user_id, message_text, message_count=0):
        if not OPENROUTER_API_KEY or not OPENROUTER_API_KEY.startswith('sk-or'):
            return None
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-4:]:
                messages.append(msg)
        
        messages.append({"role": "user", "content": message_text})
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 40
        }
        
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=25
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            if "choices" not in data or len(data["choices"]) == 0:
                return None
            
            reply = data["choices"][0]["message"]["content"]
            
            if not reply or len(reply.strip()) < 2:
                return None
            
            unwanted = ["kya chahiye", "kaise ho", "how are you", "aapka naam",
                       "namaste", "kaise hain", "what is your name", "kaun ho",
                       "what do you need", "how can i help"]
            
            if any(w in reply.lower() for w in unwanted):
                return None
            
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            if len(self.conversations[user_id]) > 10:
                self.conversations[user_id] = self.conversations[user_id][-10:]
            
            return reply
            
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            return None
