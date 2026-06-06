# shruti_bot.py
from shruti_ai import get_ai_response
import logging

logger = logging.getLogger(__name__)

class ShrutiAIBot:
    def __init__(self):
        self.conversations = {}  # {user_id: [messages]}
        self.user_info = {}      # {user_id: {name, first_seen, etc}}
    
    def get_reply(self, user_id, message_text, message_count=0):
        """Get AI reply with full conversation context"""
        
        # Create user message
        user_msg = {
            "role": "user",
            "content": message_text
        }
        
        # Initialize conversation if new user
        if user_id not in self.conversations:
            self.conversations[user_id] = []
        
        # Add user message to history
        self.conversations[user_id].append(user_msg)
        
        # Get full conversation history
        history = self.conversations[user_id]
        
        # Get AI response
        reply = get_ai_response(message_text, history, user_id)
        
        # Store assistant reply
        self.conversations[user_id].append({
            "role": "assistant",
            "content": reply
        })
        
        # Keep last 30 messages (enough context)
        if len(self.conversations[user_id]) > 30:
            self.conversations[user_id] = self.conversations[user_id][-30:]
        
        logger.info(f"💬 User {user_id} - Total msgs: {len(self.conversations[user_id])}")
        
        return reply
