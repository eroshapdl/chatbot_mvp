import os
import asyncio
from pathlib import Path
from uuid import uuid4
import json

import httpx
from fastapi import FastAPI, Form, Depends, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session
from decouple import config
from openai import OpenAI

from utils import send_message, logger
from models import SessionLocal
from db import save_conversation, get_last_messages

# ====== CONFIG ======
app = FastAPI()
Path("audio").mkdir(exist_ok=True)

# OpenAI client
client = OpenAI(api_key=config("OPENAI_API_KEY"))

# Twilio (WhatsApp)
TWILIO_SID = config("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = config("TWILIO_AUTH_TOKEN")
NGROK_URL = config("NGROK_URL")
WHATSAPP_BOT_NUMBER = config("TWILIO_NUMBER")

# Facebook
FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN")
FACEBOOK_VERIFY_TOKEN = 'facebook_verify_token_123'
FACEBOOK_PAGE_ID = "763745670161641"

#Telegram
TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN")

# Doctor persona
system_prompt = """
You are Dr. Nova, a professional and empathetic general physician.
Respond clearly and kindly to patient messages.
Keep answers concise and helpful.
"""

# DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ====== Health Check ======
@app.get("/")
async def root():
    return {"message": "Dr. Nova Bot is running - WhatsApp & Facebook and Telegram with Audio"}

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "multi-platform-bot"}

@app.on_event("startup")
async def setup_telegram_webhook():
    """Set up Telegram webhook on startup"""
    if TELEGRAM_BOT_TOKEN and NGROK_URL:
        webhook_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
        async with httpx.AsyncClient() as client_http:
            try:
                response = await client_http.post(webhook_url, json={
                    "url": f"{NGROK_URL}/telegram/webhook",
                    "allowed_updates": ["message"]
                })
                if response.status_code == 200:
                    logger.info("✅ Telegram webhook set successfully")
                else:
                    logger.error(f"❌ Failed to set Telegram webhook: {response.text}")
            except Exception as e:
                logger.error(f"❌ Error setting Telegram webhook: {e}")


# ====== Serve Audio Files ======
@app.get("/audio/{filename}")
async def get_audio(filename: str):
    audio_path = Path("audio") / filename
    if not audio_path.exists():
        return JSONResponse({"error": "File not found"}, status_code=404)
    return FileResponse(audio_path, headers={
        "Content-Type": "audio/mpeg",
        "Cache-Control": "no-cache",
        "Access-Control-Allow-Origin": "*",
    })

# ====== WhatsApp Bot ======
@app.post("/message")
async def whatsapp_reply(
    request: Request,
    Body: str = Form(None),
    MediaUrl0: str = Form(None),
    From: str = Form(None),
    db: Session = Depends(get_db)
):
    whatsapp_number = From.split("whatsapp:")[-1].strip()
    if whatsapp_number == WHATSAPP_BOT_NUMBER:
        return ""  # Ignore bot messages

    logger.info(f"WhatsApp - Incoming message from {whatsapp_number}: {Body or MediaUrl0}")

    # Fetch last messages
    last_messages = get_last_messages(db, whatsapp_number, limit=20)

    # Determine voice or text
    if MediaUrl0:
        # Audio
        audio_filename = f"{uuid4()}.ogg"
        audio_path = Path("audio") / audio_filename
        async with httpx.AsyncClient(auth=(TWILIO_SID, TWILIO_TOKEN), follow_redirects=True) as client_http:
            r = await client_http.get(MediaUrl0)
            r.raise_for_status()
            with open(audio_path, "wb") as f:
                f.write(r.content)
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(model="whisper-1", file=audio_file).text
        user_message = transcription.lower().replace("reply in voice", "").strip()
        voice_reply = True
        os.remove(audio_path)
    else:
        user_message = (Body or "").lower().replace("reply in voice", "").strip()
        voice_reply = "reply in voice" in (Body or "").lower()

    # GPT conversation
    messages = [{"role": "system", "content": system_prompt}]
    for conv in last_messages:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=400,
            temperature=0.5
        )
        chatgpt_response = response.choices[0].message.content
    except Exception as e:
        logger.error(f"WhatsApp - OpenAI API error: {e}")
        chatgpt_response = "Sorry, something went wrong. Please try again later."

    # Save conversation
    save_conversation(db, whatsapp_number, user_message, chatgpt_response)

    # Send response
    if voice_reply:
        tts_filename = f"{uuid4()}.mp3"
        tts_path = Path("audio") / tts_filename
        with client.audio.speech.with_streaming_response.create(model="tts-1", voice="nova", input=chatgpt_response) as tts_resp:
            tts_resp.stream_to_file(tts_path)
        audio_url = f"{NGROK_URL}/audio/{tts_filename}"
        send_message(whatsapp_number, audio_url, is_voice=True)

        # Delete TTS file after 30 seconds
        asyncio.create_task(remove_file_later(tts_path))
    else:
        send_message(whatsapp_number, chatgpt_response)

    return ""

# ====== Facebook Bot ======
processed_mids = set()

@app.get("/facebook/webhook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    print('tester')
    if mode == "subscribe" and token == FACEBOOK_VERIFY_TOKEN:
        print('testttttttttttt')
        return int(challenge)  # must return challenge directly
    
    return {"error": "Invalid verify token"}

@app.post("/facebook/webhook")
async def handle_facebook_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):
                sender_id = event["sender"]["id"]

                if sender_id == FACEBOOK_PAGE_ID:
                    continue  # ignore bot messages

                message = event.get("message")
                if not message or message.get("is_echo"):
                    continue  # ignore echoes

                mid = message.get("mid")
                if not mid or mid in processed_mids:
                    continue  # already processed
                processed_mids.add(mid)

                # Text messages
                if "text" in message:
                    user_msg = message["text"].replace("reply in voice", "").strip()
                    voice_reply = "reply in voice" in message["text"].lower()
                    bot_reply = await process_facebook_message(db, sender_id, user_msg)
                    if voice_reply:
                        await send_facebook_voice_message(sender_id, bot_reply)
                    else:
                        await send_facebook_text_message(sender_id, bot_reply)

                # Audio messages
                elif "attachments" in message:
                    audio_processed = False
                    for attachment in message["attachments"]:
                        if attachment.get("type") == "audio" and not audio_processed:
                            audio_url = attachment["payload"]["url"]
                            user_msg = await process_facebook_audio_message(audio_url)
                            bot_reply = await process_facebook_message(db, sender_id, user_msg)
                            await send_facebook_voice_message(sender_id, bot_reply)
                            audio_processed = True
        return JSONResponse({"status": "ok"})
    except Exception as e:
        logger.error(f"Facebook webhook error: {e}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)
    
# ====== Telegram ======
@app.post("/telegram/webhook")
async def handle_telegram_webhook(request: Request, db: Session = Depends(get_db)):
    try:
        data = await request.json()
        logger.info(f"Telegram - Incoming message")
        
        if "message" not in data:
            return JSONResponse({"status": "ok"})
        
        message = data["message"]
        chat_id = str(message["chat"]["id"])
        
        # Handle commands like /start
        if "text" in message and message["text"].startswith("/"):
            await handle_telegram_command(chat_id, message["text"])
            return JSONResponse({"status": "ok"})
        
        # Handle regular text messages
        if "text" in message:
            original_text = message["text"]
            logger.info(f"📝 Original message: '{original_text}'")
            
            user_message = original_text.replace("reply in voice", "").strip()
            voice_reply = "reply in voice" in original_text.lower()
            
            logger.info(f"🧹 Cleaned message: '{user_message}'")
            logger.info(f"🔊 Voice reply requested: {voice_reply}")
            
            bot_reply = await process_telegram_message(db, chat_id, user_message)
            
            if voice_reply:
                logger.info("🎙️ Sending VOICE message")
                await send_telegram_voice_message(chat_id, bot_reply)
            else:
                logger.info("💬 Sending TEXT message")
                await send_telegram_text_message(chat_id, bot_reply)
        
        # Handle voice messages
        elif "voice" in message:
            logger.info("🎤 Processing voice message")
            file_id = message["voice"]["file_id"]
            user_message = await process_telegram_voice_message(file_id)
            bot_reply = await process_telegram_message(db, chat_id, user_message)
            logger.info("🎙️ Replying with voice to voice message")
            await send_telegram_voice_message(chat_id, bot_reply)
            
        elif "audio" in message:
            logger.info("🎵 Processing audio message")
            file_id = message["audio"]["file_id"]
            user_message = await process_telegram_voice_message(file_id)
            bot_reply = await process_telegram_message(db, chat_id, user_message)
            logger.info("🎙️ Replying with voice to audio message")
            await send_telegram_voice_message(chat_id, bot_reply)
            
        return JSONResponse({"status": "ok"})
        
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=500)
    

# ====== Helper Functions ======
async def process_facebook_audio_message(audio_url: str) -> str:
    audio_filename = f"fb_{uuid4()}.m4a"
    audio_path = Path("audio") / audio_filename
    async with httpx.AsyncClient() as client_http:
        r = await client_http.get(audio_url)
        r.raise_for_status()
        with open(audio_path, "wb") as f:
            f.write(r.content)

    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(model="whisper-1", file=f)

    os.remove(audio_path)
    return transcription.text.strip()

async def process_facebook_message(db: Session, sender_id: str, user_message: str) -> str:
    last_messages = get_last_messages(db, sender_id, limit=20)
    messages = [{"role": "system", "content": system_prompt}]
    for conv in last_messages:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    messages.append({"role": "user", "content": user_message})

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=400,
        temperature=0.5,
    )
    bot_reply = response.choices[0].message.content
    save_conversation(db, sender_id, user_message, bot_reply)
    return bot_reply

async def send_facebook_voice_message(recipient_id: str, message: str):
    tts_filename = f"fb_{uuid4()}.mp3"
    tts_path = Path("audio") / tts_filename
    with client.audio.speech.with_streaming_response.create(model="tts-1", voice="nova", input=message) as tts_resp:
        tts_resp.stream_to_file(tts_path)
    audio_url = f"{NGROK_URL}/audio/{tts_filename}"

    async with httpx.AsyncClient() as http_client:
        await http_client.post(
            f"https://graph.facebook.com/v18.0/me/messages?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}",
            json={
                "recipient": {"id": recipient_id},
                "message": {"attachment": {"type": "audio", "payload": {"url": audio_url, "is_reusable": False}}},
            },
        )
    asyncio.create_task(remove_file_later(tts_path))

async def send_facebook_text_message(recipient_id: str, message: str):
    async with httpx.AsyncClient() as http_client:
        await http_client.post(
            f"https://graph.facebook.com/v18.0/me/messages?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}",
            json={"recipient": {"id": recipient_id}, "message": {"text": message}},
        )

async def remove_file_later(path: Path, delay: int = 30):
    await asyncio.sleep(delay)
    try:
        os.remove(path)
    except Exception as e:
        logger.error(f"Failed to delete file {path}: {e}")



async def process_telegram_voice_message(file_id: str) -> str:
    """Download and transcribe Telegram voice message"""
    audio_filename = f"tg_{uuid4()}.oga"
    audio_path = Path("audio") / audio_filename
    
    # Get file info from Telegram
    file_info_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile"
    async with httpx.AsyncClient() as client_http:
        response = await client_http.get(file_info_url, params={"file_id": file_id})
        file_data = response.json()
        
        if not file_data["ok"]:
            raise Exception(f"Failed to get file info")
        
        # Download the voice file
        file_path = file_data["result"]["file_path"]
        download_url = f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"
        download_response = await client_http.get(download_url)
        
        with open(audio_path, "wb") as f:
            f.write(download_response.content)
    
    with open(audio_path, "rb") as f:
        transcription = client.audio.transcriptions.create(model="whisper-1", file=f)
    
    os.remove(audio_path)
    return transcription.text.strip()

async def process_telegram_message(db: Session, chat_id: str, user_message: str) -> str:
    """Process Telegram message and generate response"""
    last_messages = get_last_messages(db, f"telegram_{chat_id}", limit=20)
    messages = [{"role": "system", "content": system_prompt}]
    for conv in last_messages:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    messages.append({"role": "user", "content": user_message})
    
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        max_tokens=400,
        temperature=0.5,
    )
    bot_reply = response.choices[0].message.content
    save_conversation(db, f"telegram_{chat_id}", user_message, bot_reply)
    return bot_reply

async def send_telegram_voice_message(chat_id: str, message: str):
    """Send voice message to Telegram user"""
    tts_filename = f"tg_{uuid4()}.mp3"
    tts_path = Path("audio") / tts_filename
    
    with client.audio.speech.with_streaming_response.create(model="tts-1", voice="nova", input=message) as tts_resp:
        tts_resp.stream_to_file(tts_path)
    
    # Send as voice message directly to Telegram
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendVoice"
    
    async with httpx.AsyncClient() as client_http:
        with open(tts_path, "rb") as audio_file:
            files = {"voice": (tts_filename, audio_file, "audio/mpeg")}
            data = {"chat_id": chat_id}
            await client_http.post(url, files=files, data=data)
    
    asyncio.create_task(remove_file_later(tts_path))

async def send_telegram_text_message(chat_id: str, message: str):
    """Send text message to Telegram user"""
    async with httpx.AsyncClient() as client_http:
        await client_http.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": message},
        )

async def handle_telegram_command(chat_id: str, command: str):
    """Handle Telegram bot commands like /start"""
    if command == "/start":
        welcome_msg = """👋 Hello! I'm Dr. Nova, your AI medical assistant.

🩺 I can help with general health questions
💊 Medication information  
🏥 When to see a doctor
🗣️ Voice messages (send voice notes!)

Type "reply in voice" for audio responses.
How can I help you today?"""
        await send_telegram_text_message(chat_id, welcome_msg)
        
    elif command == "/help":
        help_msg = """📋 How to use Dr. Nova:

• Send text or voice messages
• Ask about symptoms or health concerns  
• Type "reply in voice" for audio responses
• I remember our conversation

⚠️ Important: For emergencies, contact a doctor immediately."""
        await send_telegram_text_message(chat_id, help_msg)



# ====== Run Server ======
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
