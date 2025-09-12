import requests
from decouple import config
from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from utils import logger   # you already have this
from models import SessionLocal
from db import save_conversation, get_last_messages
from openai import OpenAI

# 🔹 App instance (can be the same FastAPI app as WhatsApp)
app = FastAPI()

# 🔹 Facebook + OpenAI configs
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = config("FACEBOOK_VERIFY_TOKEN")
client = OpenAI(api_key=config("OPENAI_API_KEY"))

# 🔹 Doctor persona (reuse same as WhatsApp)
system_prompt = """
You are Dr. Emily, a professional and empathetic general physician.
You respond clearly and kindly to patient messages.
- Always provide accurate medical information and advice.
- For new or ongoing health problems, suggest safe home care, OTC remedies, or lifestyle measures for minor, common issues.
- Warn the patient to see a doctor if symptoms are severe, unusual, sudden, or worsen.
- Remember conversation history for context.
- Use simple, friendly language (no slang/emojis).
- Keep answers concise, helpful, and practical.
- If symptoms suggest an emergency, instruct immediate medical care.
"""

# 🔹 DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/facebook/webhook")
async def verify_webhook(request: Request):
    """Facebook verification endpoint"""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return int(challenge)
    return JSONResponse(content={"error": "Invalid verification"}, status_code=403)


@app.post("/facebook/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    """Handles messages from Facebook Messenger"""
    data = await request.json()
    logger.info(f"Incoming Facebook data: {data}")

    if "entry" in data:
        for entry in data["entry"]:
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event["sender"]["id"]

                # If user sends a text message
                if "message" in messaging_event and "text" in messaging_event["message"]:
                    user_message = messaging_event["message"]["text"]

                    # 1. Get last conversation history
                    last_messages = get_last_messages(db, sender_id, limit=20)

                    # 2. Build GPT context
                    messages = [{"role": "system", "content": system_prompt}]
                    for conv in last_messages:
                        messages.append({"role": "user", "content": conv.message})
                        messages.append({"role": "assistant", "content": conv.response})
                    messages.append({"role": "user", "content": user_message})

                    # 3. Get GPT reply
                    try:
                        response = client.chat.completions.create(
                            model="gpt-4.1-mini",
                            messages=messages,
                            max_tokens=400,
                            temperature=0.5,
                        )
                        bot_reply = response.choices[0].message.content
                        logger.info(f"FB Bot Reply: {bot_reply}")
                    except Exception as e:
                        logger.error(f"OpenAI API error: {e}")
                        bot_reply = "Sorry, something went wrong."

                    # 4. Save conversation
                    save_conversation(db, sender_id, user_message, bot_reply)

                    # 5. Send reply back to Messenger
                    send_facebook_message(sender_id, bot_reply)

    return JSONResponse(content={"status": "ok"})


def send_facebook_message(recipient_id: str, message: str):
    """Send a message back to Facebook Messenger"""
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        logger.error(f"Error sending message to FB: {response.text}")
