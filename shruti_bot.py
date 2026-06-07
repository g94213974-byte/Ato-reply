# shruti_bot.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

# ===== NEW SYSTEM PROMPTS - FULLY MODIFIED =====

SYSTEM_PROMPT_FIRST = """You are Shruti, a very cute and sweet Indian girlfriend-like girl on Telegram.
This is the FIRST message to a customer.

CRITICAL RULES (FOLLOW STRICTLY):
1. NEVER ask "what do you need" or "kya chahiye" — assume they came for service
2. ALWAYS ask "kitna time chahiye baby?" (how many minutes?)
3. Be VERY cute, sweet, flirty — make them fall for you
4. Keep it SHORT (5-10 words max)
5. Always push toward payment

EXAMPLES (copy these exactly):
- "Hii baby 😘 Kitna time chahiye aapko? ❤️"
- "Hello baby 😊 Aap service lene aaye na? Kitna minute? 🔥"
- "Hii baby 😘 Direct batao kitna minute chahiye? Payment karo maza lo 😉"
- "Hey baby 🔥 Kitna time lena hai? Batao na 😘"

REMEMBER: Never ask "kya chahiye". Always ask "kitna time"."""

SYSTEM_PROMPT_PAYMENT = """You are Shruti, a cute Indian girlfriend who ONLY talks about payment and service.

CRITICAL RULES (FOLLOW STRICTLY):
1. Keep replies VERY SHORT (5-10 words max)
2. ALWAYS push for payment
3. Be sweet, flirty, cute
4. Never chat casually — only payment talk
5. Never give free content

EXAMPLES (copy these exactly):
- "Payment karo baby, phir full maja dungi 😘🔥"
- "UPI se pay karo baby, QR bhej du? ❤️"
- "Pehle payment karo baby, phir baat hogi 😊"
- "Payment screenshot bhejo baby, phir service milega 🔥"
- "Demo ₹19, VC 10min ₹49. Pay karo baby 😘"
- "Payment karo na baby, bahut cute hoon main trust karo ❤️"
- "Pay karo baby, phir dekhna maza aayega 😉🔥"

REMEMBER: Always mention payment. Be cute but firm."""

SYSTEM_PROMPT_NORMAL = """You are Shruti, a very cute and sweet Indian girlfriend-like girl on Telegram.

CRITICAL RULES (FOLLOW STRICTLY):
1. NEVER ask "kya chahiye aapko?" — this is FORBIDDEN
2. NEVER ask "how are you?" or "kaise ho?" — this is FORBIDDEN
3. ALWAYS assume they came for service
4. ALWAYS ask "kitna time chahiye?" or talk about payment
5. Be VERY cute, flirty, sweet — make them fall in love with you
6. Keep replies SHORT (8-12 words max)
7. Every reply must mention payment OR time
8. Use emojis: 😘 ❤️ 🔥 😊 😉

EXAMPLES (copy these exactly):
- "Kitna time chahiye aapko baby? 10 min ya 20? 😘"
- "Payment karo na baby 😊 Bahut maza ayega 🔥"
- "Aajao baby, payment karo main ready hoon ❤️"
- "Kitna minute lena hai? Batao na baby 😘"
- "Payment karo phir dekhna kitna cute hoon main 🔥"
- "Service leni hai na? Toh payment karo baby 😘"
- "10 min ₹49, 20 min ₹59. Kitna lena hai baby? ❤️"

REMEMBER: NEVER say "kya chahiye". Always payment/time focused."""

# For free pic requests
SYSTEM_PROMPT_PIC = """You are Shruti, a cute Indian girl. Customer is asking for FREE pictures.

RULES:
1. NEVER give free content
2. Say pic is not free
3. Push them to pay for VC
4. Be cute but firm

EXAMPLES:
- "Pic free nahi hai baby 😘 Payment karo, VC mein full maja lo 🔥"
- "Free pic nahi milta baby 😊 Payment karo phir dikha dungi ❤️"
- "Pic nahi free baby 😘 Pehle payment karo 😉"

REMEMBER: Always refuse free content sweetly."""

# For real meet requests
SYSTEM_PROMPT_MEET = """You are Shruti, an online service provider. Customer is asking for REAL MEETING.

RULES:
1. POLITELY refuse real meet
2. Say only online service available
3. Push for online VC payment

EXAMPLES:
- "Baby real meet nahi, only online service hai 😊"
- "Real meet available nahi baby 😘 Online mein full maza lo 🔥"
- "Sorry baby, online service only. Payment karo na 😘"

REMEMBER: Never agree to real meet. Only online."""


PAYMENT_KEYWORDS = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'phonepe', 'gpay', 
                    'google pay', 'kaha', 'kaise', 'account', 'bank', 'send', 'bhejo',
                    'screenshot', 'payment kar', 'pay karo', 'pay kaise', 'kaha pay',
                    'kaise pay', 'method', 'transfer', 'rupees', 'rs', '₹', 'dham',
                    'send karo', 'money', 'paise', 'payment method']

PIC_KEYWORDS = ['pic', 'pics', 'picture', 'photo', 'image', 'nude pic', 'nude photo',
                'naked', 'xxx pic', 'sexy pic', 'dikhao', 'show', 'dikha',
                'nangi', 'nude image', 'boob', 'boobs', 'dikha do']

MEET_KEYWORDS = ['real', 'meet', 'mil', 'real meet', 'real sex', 'real xxx', 'real life',
                 'personal', 'real life meet', 'aao', 'aana', 'ghar', 'location', 'aaja',
                 'real service', 'offline', 'direct', 'face to face', 'real video',
                 'aaja mil', 'milna', 'personal meet', 'live']


class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}
        if not OPENROUTER_API_KEY:
            logger.error("❌ OPENROUTER_API_KEY is EMPTY!")
        elif not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error(f"❌ OPENROUTER_API_KEY invalid: {OPENROUTER_API_KEY[:10]}...")
        else:
            logger.info(f"✅ OpenRouter API Key found")
    
    def is_payment_related(self, text):
        """Check if message is about payment"""
        text_lower = text.lower()
        for kw in PAYMENT_KEYWORDS:
            if kw in text_lower:
                return True
        return False
    
    def is_pic_request(self, text):
        """Check if user is asking for free pictures"""
        text_lower = text.lower()
        for kw in PIC_KEYWORDS:
            if kw in text_lower:
                return True
        return False
    
    def is_meet_request(self, text):
        """Check if user wants real meeting"""
        text_lower = text.lower()
        for kw in MEET_KEYWORDS:
            if kw in text_lower:
                return True
        return False
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user message"""
        
        if not OPENROUTER_API_KEY or not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error("❌ Invalid API Key")
            return None
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # ---- Choose the right system prompt based on message ----
        
        if self.is_pic_request(message_text):
            # User asking for free pics
            system = SYSTEM_PROMPT_PIC
            max_tok = 50
            
        elif self.is_meet_request(message_text):
            # User asking for real meeting
            system = SYSTEM_PROMPT_MEET
            max_tok = 50
            
        elif message_count == 0:
            # First message - direct service approach
            system = SYSTEM_PROMPT_FIRST
            max_tok = 55
            
        elif self.is_payment_related(message_text):
            # User is talking about payment - only payment talk
            system = SYSTEM_PROMPT_PAYMENT
            max_tok = 50
            
        else:
            # Normal chat - but always payment/time focused
            system = SYSTEM_PROMPT_NORMAL
            max_tok = 60
        
        # Build messages
        messages = [{"role": "system", "content": system}]
        
        # Add conversation history (last 6 messages only, not first message context)
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-6:]:
                messages.append(msg)
        
        messages.append({"role": "user", "content": message_text})
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.85,
            "max_tokens": max_tok,
            "top_p": 0.95
        }
        
        try:
            logger.info(f"📤 msg#{message_count}: {message_text[:35]}...")
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"❌ OpenRouter HTTP {response.status_code}")
                return None
            
            data = response.json()
            
            if "choices" not in data or len(data["choices"]) == 0:
                return None
            
            reply = data["choices"][0]["message"]["content"]
            
            if not reply or len(reply.strip()) < 2:
                return None
            
            # ---- FILTER UNWANTED REPLIES ----
            unwanted_phrases = [
                "kya chahiye aapko", "kya chahiye", "kaise ho", "how are you",
                "kya kar rahe", "aapka naam", "namaste", "kaise hain",
                "what is your name", "kaun ho", "kon ho", "kaun hain aap",
                "what do you need", "what can i do", "how can i help",
                "aap kya chahte", "batao kya chahiye", "bolo kya chahiye",
                "kaise ho aap", "kya karte ho", "kya kar rahe ho"
            ]
            
            reply_lower = reply.lower().strip()
            
            if any(phrase in reply_lower for phrase in unwanted_phrases):
                logger.warning(f"⚠️ Blocked unwanted reply: {reply[:40]}...")
                return None  # main.py will use its own fallback
            
            # ---- Save conversation ----
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            # Keep only last 16 messages
            if len(self.conversations[user_id]) > 16:
                self.conversations[user_id] = self.conversations[user_id][-16:]
            
            logger.info(f"✅ Reply: {reply[:55]}...")
            return reply
            
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            return None
