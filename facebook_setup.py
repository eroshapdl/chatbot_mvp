from fastapi import FastAPI, Request, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.orm import Session
from utils import logger
from models import SessionLocal
from db import save_conversation, get_last_messages
from openai import OpenAI
from decouple import config
import requests

app = FastAPI()

# Configs
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN")
VERIFY_TOKEN = config("FACEBOOK_VERIFY_TOKEN")
client = OpenAI(api_key=config("OPENAI_API_KEY"))

system_prompt = """ You are Dr. Emily, a professional and empathetic general physician. You respond clearly and kindly to patient messages. - Always provide accurate medical information and advice. - For new or ongoing health problems, suggest safe home care, OTC remedies, or lifestyle measures for minor, common issues. - Warn the patient to see a doctor if symptoms are severe, unusual, sudden, or worsen. - Remember conversation history for context. - Use simple, friendly language (no slang/emojis). - Keep answers concise, helpful, and practical. - If symptoms suggest an emergency, instruct immediate medical care. """

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ✅ Facebook webhook GET (verification) - FIXED
@app.get("/facebook/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    
    logger.info(f"Webhook verification - Mode: {mode}, Token: {token}, Challenge: {challenge}")
    logger.info(f"Expected token: {VERIFY_TOKEN}")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        logger.info("Webhook verification successful")
        # Return the challenge as plain text, not JSON
        return PlainTextResponse(content=challenge)
    else:
        logger.error(f"Webhook verification failed - mode: {mode}, token: {token}")
        return JSONResponse(content={"error": "Invalid verification"}, status_code=403)


# ✅ Facebook webhook POST (messages) - FIXED
@app.post("/facebook/webhook")
async def handle_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.json()
    logger.info(f"Incoming Facebook data: {data}")

    if "entry" in data:
        for entry in data["entry"]:
            for messaging_event in entry.get("messaging", []):
                sender_id = messaging_event["sender"]["id"]

                if "message" in messaging_event and "text" in messaging_event["message"]:
                    user_message = messaging_event["message"]["text"]
                    logger.info(f"Received message from {sender_id}: {user_message}")

                    # GPT logic
                    last_messages = get_last_messages(db, sender_id, limit=20)
                    messages = [{"role": "system", "content": system_prompt}]
                    
                    for conv in last_messages:
                        messages.append({"role": "user", "content": conv.message})
                        messages.append({"role": "assistant", "content": conv.response})
                    
                    messages.append({"role": "user", "content": user_message})

                    try:
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",  # Fixed model name
                            messages=messages,
                            max_tokens=400,
                            temperature=0.5,
                        )
                        bot_reply = response.choices[0].message.content
                        logger.info(f"Generated response: {bot_reply}")
                    except Exception as e:
                        logger.error(f"OpenAI API error: {e}")
                        bot_reply = "Sorry, I'm having technical difficulties. Please try again later."

                    # Save conversation and send response
                    save_conversation(db, sender_id, user_message, bot_reply)
                    send_facebook_message(sender_id, bot_reply)

    return JSONResponse(content={"status": "ok"})


def send_facebook_message(recipient_id: str, message: str):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id}, 
        "message": {"text": message}
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            logger.info(f"Message sent successfully to {recipient_id}")
        else:
            logger.error(f"Error sending message to FB: {response.status_code} - {response.text}")
    except Exception as e:
        logger.error(f"Exception sending message: {e}")


# Health check endpoint
@app.get("/")
async def root():
    return {"message": "Dr. Emily Bot is running"}


# Additional health check for webhook
@app.get("/health")
async def health():
    return {"status": "healthy", "service": "facebook-webhook"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)