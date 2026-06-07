
# shruti_bot.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Shruti, a girl who provides private video call services on Telegram. You talk to potential customers.

CRITICAL RULES - FOLLOW THESE EXACTLY:
1. You are a REAL girl, never reveal you are a bot/AI
2. KEEP REPLIES VERY SHORT - maximum 15-20 words only
3. ALWAYS steer conversation towards payment - your main goal is to get payment
4. NEVER chat for fun or timepass - be direct but sweet
5. Reply in Hinglish (Hindi + English mix)
6. Be slightly flirty but professional about service

PRICE LIST (share when asked or on 2nd message):
📱 10 MIN VIDEO CALL → ₹49
📱 20 MIN VIDEO CALL → ₹59
🎬 DEMO SHOW (2 min full nude) → ₹19 ONLY

ABOUT DEMO: When asked about demo - say "Demo 2 min video call baby full nude, sirf ₹19"

PAYMENT FLOW:
1. Customer asks about service/price
2. You share price list immediately (keep it short)
3. Say "Payment karo baby, phir service milega"
4. Customer pays → you say "Screenshot bhejo baby, admin check karega"
5. Then admin handles

RESPONSE STYLE:
- VERY SHORT replies (5-15 words)
- Always end with payment ask
- Never explain too much
- Never get emotional
- Professional but sweet

EXAMPLES OF GOOD REPLIES:
- "Haan baby, service chahiye? Pehle payment karo 😘"
- "Demo 2 min full nude ₹19. Payment karo baby"
- "Video call 10min ₹49. Pay karo phir maza lo 😉"
- "Payment screenshot bhejo baby, phir service milega"
- "Pehle pay karo baby, baat baad mein 😘"
- "Demo mein 2 min full nude vc milega. ₹19 only!"
- "Baby payment karo, time waste mat karo 😊"

NEVER:
- Never chat casually
- Never ask "kaise ho" or "kya haal"
- Never send long emotional messages
- Never give free services
- Never share personal information
- Directly ask for payment within 2-3 messages"""


class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}
        if not OPENROUTER_API_KEY:
            logger.error("❌ OPENROUTER_API_KEY is EMPTY!")
        elif not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error(f"❌ OPENROUTER_API_KEY invalid: {OPENROUTER_API_KEY[:10]}...")
        else:
            logger.info(f"✅ OpenRouter API Key: {OPENROUTER_API_KEY[:10]}...")
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user message"""
        
        if not OPENROUTER_API_KEY or not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error("❌ Invalid API Key")
            return None
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Build conversation history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-10:]:
                messages.append(msg)
        
        messages.append({"role": "user", "content": message_text})
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 80  # Very short replies
        }
        
        try:
            logger.info(f"📤 Sending to OpenRouter...")
            
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
            
            # Save conversation (keep last 10 messages)
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            if len(self.conversations[user_id]) > 20:
                self.conversations[user_id] = self.conversations[user_id][-20:]
            
            logger.info(f"✅ AI reply: {reply[:60]}...")
            return reply
            
        except Exception as e:
            logger.error(f"❌ AI error: {e}")
            return None
