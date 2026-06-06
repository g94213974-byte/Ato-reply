# shruti_ai.py
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

Price list (only if directly asked):
- 10 min video call: ₹49
- 20 min video call: ₹59
- Demo show: ₹19

You are Shruti - a real, flirty Indian girl!"""

def get_ai_response(user_message, conversation_history=None, user_id=None):
    """Get AI response from Open Router"""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    if conversation_history:
        for msg in conversation_history[-25:]:
            messages.append(msg)
    
    messages.append({"role": "user", "content": user_message})
    
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 200
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
        logger.error(f"❌ Open Router API error: {e}")
        return "baby baat toh karo... kya ho gaya? 😘"
