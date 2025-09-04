from sqlalchemy.orm import Session
from models import Conversation
from sqlalchemy import desc
import logging

logger = logging.getLogger(__name__)

def save_conversation(db: Session, user_id: str, message: str, response: str):
    """
    Save conversation with platform prefix
    user_id format: 'wa_phonenumber' for WhatsApp, 'fb_userid' for Facebook Messenger
    """
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
    """
    Get last messages for a user (works for both WhatsApp and Facebook Messenger)
    user_id format: 'wa_phonenumber' for WhatsApp, 'fb_userid' for Facebook Messenger
    """
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

def get_platform_from_user_id(user_id: str):
    """Extract platform from user_id"""
    if user_id.startswith('wa_'):
        return 'whatsapp'
    elif user_id.startswith('fb_'):
        return 'facebook'
    else:
        return 'unknown'

def get_user_stats(db: Session):
    """Get statistics about platform usage"""
    try:
        from sqlalchemy import func
        
        stats = (
            db.query(
                func.substr(Conversation.sender, 1, 3).label('platform'),
                func.count(Conversation.id).label('message_count'),
                func.count(func.distinct(Conversation.sender)).label('unique_users')
            )
            .group_by(func.substr(Conversation.sender, 1, 3))
            .all()
        )
        
        return {
            stat.platform: {
                'message_count': stat.message_count,
                'unique_users': stat.unique_users
            }
            for stat in stats
        }
    except Exception as e:
        logger.error(f"Error fetching user stats: {e}")
        return {}