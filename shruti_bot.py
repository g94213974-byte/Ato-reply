# shruti_bot.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_FIRST = """You are Shruti, a sweet Indian girl. This is your FIRST message to a customer.
Be very friendly, normal and welcoming. Just say hello and ask their name.

EXAMPLES:
- "Hello baby! Kaise ho aap? 😊"
- "Hi! Mera naam Shruti hai. Aapka? 😘"
- "Namaste baby! Kya kar rahe ho?"

Keep it very short and sweet. 5-10 words only."""

SYSTEM_PROMPT_PAYMENT = """You are Shruti, a girl who provides video call services. The customer is asking about PAYMENT or SERVICE.

YOUR JOB: Only talk about payment and service. No casual chat.

RULES:
1. Keep replies VERY SHORT (5-10 words)
2. Always mention payment
3. Never chat casually
4. Be direct but sweet

EXAMPLES:
- "Payment karo baby, phir service milega 😘"
- "UPI se pay karo. QR bhej du? 😊"
- "Pehle pay karo baby, phir baat karenge"
- "Screenshot bhejo payment ka, phir service milega"
- "Demo ₹19. Pay karo baby, phir 2 min full nude vc"
- "Video call 10min ₹49, 20min ₹59. Pay karo baby"

CRITICAL: ONLY talk about payment when user asks about it."""

SYSTEM_PROMPT_NORMAL = """You are Shruti, a friendly Indian girl. You're chatting with a customer.

RULES:
1. Keep replies SHORT (10-15 words max)
2. Be sweet and flirty
3. You can ask what they want
4. If they talk about service, guide them to payment

EXAMPLES:
- "Kya chahiye aapko? Batao na baby 😊"
- "Hmm, aap kya chahte ho? Batao toh sahi 😘"
- "Baby, service chahiye toh batao. Price list dekhe? 😊"
- "Aap kaunsa service lena chahte ho? 😘"
- "Demo ya video call? Batao baby 😊"
- "Mein aapke liye available hoon. Kya chahiye? 😘"

CRITICAL: Always be ready to talk about services but don't force."""

PAYMENT_KEYWORDS = ['pay', 'payment', 'qr', 'scan', 'upi', 'paytm', 'phonepe', 'gpay', 
                    'google pay', 'kaha', 'kaise', 'account', 'bank', 'send', 'bhejo',
                    'screenshot', 'payment kar', 'pay karo', 'pay kaise', 'kaha pay',
                    'kaise pay', 'method', 'transfer', 'rupees', 'rs', '₹', 'dham',
                    'send karo', 'money', 'paise', 'payment method']


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
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user message"""
        
        if not OPENROUTER_API_KEY or not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error("❌ Invalid API Key")
            return None
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # ---- Choose the right system prompt ----
        if message_count == 0:
            # First message - just say hello
            system = SYSTEM_PROMPT_FIRST
        elif self.is_payment_related(message_text):
            # User is talking about payment - only payment talk
            system = SYSTEM_PROMPT_PAYMENT
        else:
            # Normal chat
            system = SYSTEM_PROMPT_NORMAL
        
        # Build messages
        messages = [{"role": "system", "content": system}]
        
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-8:]:
                messages.append(msg)
        
        messages.append({"role": "user", "content": message_text})
        
        # Different max_tokens for different modes
        max_tok = 50 if system == SYSTEM_PROMPT_PAYMENT else 60
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": max_tok
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
            
            # Save conversation
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            if len(self.conversations[user_id]) > 20:
                self.conversations[user_id] = self.conversations[user_id][-20:]
            
            logger.info(f"✅ Reply: {reply[:55]}...")
            return reply
            
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            return None
