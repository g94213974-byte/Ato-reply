# shruti_bot.py
from shruti_ai import get_ai_response
import logging

logger = logging.getLogger(__name__)

class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}
        self.paid_users = set()
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply for a user"""
        user_msg = {
            "role": "user",
            "content": message_text
        }
        
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        
        self.conversations[user_id].append(user_msg)
        history = self.conversations[user_id]
        
        reply = get_ai_response(message_text, history, user_id)
        
        self.conversations[user_id].append({
            "role": "assistant",
            "content": reply
        })
        
        if len(self.conversations[user_id]) > 20:
            self.conversations[user_id] = self.conversations[user_id][-20:]
        
        return reply
