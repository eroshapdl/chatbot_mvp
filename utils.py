# Standard library import
import logging
import httpx
# Third-party imports
from twilio.rest import Client
from decouple import config


# Find your Account SID and Auth Token at twilio.com/console
# and set the environment variables. See http://twil.io/secure
account_sid = config("TWILIO_ACCOUNT_SID")
auth_token = config("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token)
twilio_number = config('TWILIO_NUMBER')


# Facebook Messenger setup
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN")

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Sending message logic through Twilio Messaging API
def send_message(to_number, body_text, is_voice=False):
    try:
        if is_voice:
            # Twilio needs public URL for media messages; for MVP, you can upload temporarily via ngrok or a public hosting
            # Here, you can save audio to a temp file and serve via FastAPI endpoint if needed
            message = client.messages.create(
                from_=f"whatsapp:{twilio_number}",
                media_url=[body_text],
                to=f"whatsapp:{to_number}"
            )
        else:
            message = client.messages.create(
            from_=f"whatsapp:{twilio_number}",
            body=body_text,
            to=f"whatsapp:{to_number}"
            )


        
        logger.info(f"Message sent to {to_number}: {message.body}")
    except Exception as e:
        logger.error(f"Error sending message to {to_number}: {e}")


# Facebook Messenger messaging function
async def send_facebook_message(recipient_id, message_text):
    """Send message via Facebook Messenger Graph API"""
    try:
        url = f"https://graph.facebook.com/v18.0/me/messages"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message_text},
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN
        }
        
        async with httpx.AsyncClient() as http_client:
            response = await http_client.post(url, json=payload)
            response.raise_for_status()
            
        logger.info(f"Facebook message sent to {recipient_id}: {message_text}")
        return response.json()
        
    except Exception as e:
        logger.error(f"Error sending Facebook message to {recipient_id}: {e}")
        return None


# Synchronous version for backward compatibility
def send_facebook_message_sync(recipient_id, message_text):
    """Synchronous version of Facebook message sending"""
    import requests
    
    try:
        url = f"https://graph.facebook.com/v18.0/me/messages"
        
        payload = {
            "recipient": {"id": recipient_id},
            "message": {"text": message_text},
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        logger.info(f"Facebook message sent to {recipient_id}: {message_text}")
        return response.json()
        
    except Exception as e:
        logger.error(f"Error sending Facebook message to {recipient_id}: {e}")
        return None


# Function to set up Facebook Messenger welcome message
def setup_facebook_welcome_message():
    """Set up automated welcome message for Facebook Messenger"""
    import requests
    
    try:
        url = f"https://graph.facebook.com/v18.0/me/messenger_profile"
        
        payload = {
            "get_started": {"payload": "GET_STARTED"},
            "greeting": [
                {
                    "locale": "default",
                    "text": "Hello! I'm Dr. Emily, your AI medical assistant. I'm here to help answer your health questions and provide medical guidance. How can I assist you today?"
                }
            ],
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN
        }
        
        response = requests.post(url, json=payload)
        response.raise_for_status()
        
        logger.info("Facebook welcome message set up successfully")
        return response.json()
        
    except Exception as e:
        logger.error(f"Error setting up Facebook welcome message: {e}")
        return None