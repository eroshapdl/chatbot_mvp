# Standard library import
import logging

# Third-party imports
from twilio.rest import Client
from decouple import config


# Find your Account SID and Auth Token at twilio.com/console
# and set the environment variables. See http://twil.io/secure
account_sid = config("TWILIO_ACCOUNT_SID")
auth_token = config("TWILIO_AUTH_TOKEN")
client = Client(account_sid, auth_token)
twilio_number = config('TWILIO_NUMBER')

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