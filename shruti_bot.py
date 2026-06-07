# shruti_bot.py
import requests
import json
import logging
import random
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are Shruti, a REAL Indian girl who does video calls. You talk to customers on Telegram.

CRITICAL RULES:
1. You are 100% HUMAN, never reveal you are a bot/AI
2. READ the full conversation history before replying
3. Give UNIQUE reply every time - NEVER repeat yourself
4. Understand what customer is saying and reply accordingly
5. Be flirty, intelligent, use Hinglish (Hindi+English)
6. NEVER give payment details - say "check my profile"
7. Keep replies natural and varied
8. Reply in the same language as the customer

Price list (only if directly asked):
- 10 min video call: ₹49
- 20 min video call: ₹59
- Demo show: ₹19

You are Shruti - a real, flirty Indian girl!"""


class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}
        # Check API key on init
        if not OPENROUTER_API_KEY:
            logger.error("❌ OPENROUTER_API_KEY is EMPTY! Check config.py")
        elif not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error(f"❌ OPENROUTER_API_KEY looks invalid: {OPENROUTER_API_KEY[:10]}...")
        else:
            logger.info(f"✅ OpenRouter API Key found: {OPENROUTER_API_KEY[:10]}...")
        logger.info(f"🧠 Model: {OPENROUTER_MODEL}")
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user message"""
        
        # ===== DEBUG: Log what's happening =====
        logger.info(f"🔍 get_reply called for user {user_id}: {message_text[:50]}...")
        
        if not OPENROUTER_API_KEY:
            logger.error("❌ OPENROUTER_API_KEY is missing!")
            return None
            
        if not OPENROUTER_API_KEY.startswith('sk-or'):
            logger.error(f"❌ OPENROUTER_API_KEY format invalid: {OPENROUTER_API_KEY[:15]}...")
            return None
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Build conversation history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-20:]:
                messages.append(msg)
        
        messages.append({"role": "user", "content": message_text})
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 150
        }
        
        try:
            logger.info(f"📤 Sending to OpenRouter...")
            
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.info(f"📥 OpenRouter response status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"❌ OpenRouter HTTP {response.status_code}: {response.text[:300]}")
                return None
            
            data = response.json()
            
            if "choices" not in data or len(data["choices"]) == 0:
                logger.error(f"❌ No choices in response")
                return None
            
            reply = data["choices"][0]["message"]["content"]
            
            if not reply or len(reply.strip()) < 2:
                logger.warning("⚠️ Empty reply from OpenRouter")
                return None
            
            # Save conversation
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            if len(self.conversations[user_id]) > 50:
                self.conversations[user_id] = self.conversations[user_id][-50:]
            
            logger.info(f"✅ AI reply: {reply[:60]}...")
            return reply
            
        except requests.exceptions.Timeout:
            logger.error("❌ OpenRouter timeout!")
            return None
        except requests.exceptions.ConnectionError:
            logger.error("❌ OpenRouter connection error - Check internet/API endpoint")
            return None
        except Exception as e:
            logger.error(f"❌ AI error: {e}", exc_info=True)
            return None
