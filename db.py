from sqlalchemy.orm import Session
from models import Conversation
from sqlalchemy import desc
import logging

logger = logging.getLogger(__name__)

def save_conversation(db: Session, user_id: str, message: str, response: str):
    try:
        conv = Conversation(sender=user_id, message=message, response=response)
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv
    except Exception as e:
        db.rollback()  # <-- rollback transaction on error
        logger.error(f"Error saving conversation: {e}")
        return None

def get_last_messages(db: Session, user_id: str, limit: int = 20):
    if not user_id:
        return []

    try:
        results = (
            db.query(Conversation)
            .filter(Conversation.sender == str(user_id))
            .order_by(desc(Conversation.created_at))
            .limit(limit)
            .all()
        )
        return results[::-1]  # oldest first
    except Exception as e:
        db.rollback()  # <-- rollback here too
        logger.error(f"Error fetching last messages: {e}")
        return []
