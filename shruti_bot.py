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
        self.conversations = {}  # user_id -> list of messages
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user message"""
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Build conversation history
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        
        # Add conversation history if exists
        if user_id in self.conversations:
            for msg in self.conversations[user_id][-20:]:
                messages.append(msg)
        
        # Add current user message
        messages.append({"role": "user", "content": message_text})
        
        payload = {
            "model": OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.9,
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
            reply = data["choices"][0]["message"]["content"]
            
            # Save to conversation history
            if user_id not in self.conversations:
                self.conversations[user_id] = []
            self.conversations[user_id].append({"role": "user", "content": message_text})
            self.conversations[user_id].append({"role": "assistant", "content": reply})
            
            # Keep only last 50 messages
            if len(self.conversations[user_id]) > 50:
                self.conversations[user_id] = self.conversations[user_id][-50:]
            
            return reply
            
        except Exception as e:
            logger.error(f"❌ OpenRouter API error: {e}")
            # Return None - main.py will handle with contextual reply
            return None
