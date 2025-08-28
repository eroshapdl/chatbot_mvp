import os
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import FastAPI, Form, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from decouple import config
from openai import OpenAI

from utils import send_message, logger
from models import SessionLocal
from db import save_conversation, get_last_messages

app = FastAPI()
Path("audio").mkdir(exist_ok=True)

# OpenAI client
client = OpenAI(api_key=config("OPENAI_API_KEY"))

# Twilio credentials
TWILIO_SID = config("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = config("TWILIO_AUTH_TOKEN")
NGROK_URL = config("NGROK_URL")  # e.g., https://abcd1234.ngrok.io

# Doctor persona
system_prompt = """
You are Dr. Emily, a professional and empathetic general physician.
You respond clearly and kindly to patient messages.

- Always provide accurate medical information and advice.
- For new or ongoing health problems, you may suggest safe home care, over-the-counter remedies, or lifestyle measures for minor, common issues, without needing a list of conditions.
- Always ask clarifying questions only if necessary to give safe guidance.
- Warn the patient to see a doctor promptly if symptoms are severe, unusual, sudden, or worsen.
- Remember all previous messages from the same patient in this conversation to give informed advice.
- Use simple, friendly language. Never use slang, emojis, or em-dashes.
- Keep answers concise, helpful, and practical.
- Suggest prescription-only medications or anything but advise to consult doctor.
- If the patient’s symptoms could be an emergency, instruct them to seek urgent medical care immediately.
- You may respond in text, but know that the system can convert your text into voice automatically.
- Never say you can only respond in text. Just provide the answer in normal text.
"""

# DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/audio/{filename}")
async def get_audio(filename: str):
    return FileResponse(f"audio/{filename}")


@app.post("/message")
async def reply(
    request: Request,
    Body: str = Form(None),
    MediaUrl0: str = Form(None),
    db: Session = Depends(get_db)
):
    """
    Handles both text and audio messages from WhatsApp.
    MediaUrl0 is sent by Twilio if user sends audio.
    """
    form_data = await request.form()
    whatsapp_number = form_data.get("From", "").split("whatsapp:")[-1].strip()
    logger.info(f"Incoming message from {whatsapp_number}: {Body or MediaUrl0}")

    # Step 1: Retrieve last 50 messages for context
    last_messages = get_last_messages(db, whatsapp_number, limit=50)

    # Step 2: Detect message type
    if MediaUrl0:
        # Download audio with Twilio auth
        audio_filename = f"{uuid4()}.ogg"
        audio_path = Path("audio") / audio_filename
        async with httpx.AsyncClient(auth=(TWILIO_SID, TWILIO_TOKEN), follow_redirects = True) as client_http:
            r = await client_http.get(MediaUrl0)
            r.raise_for_status()
            with open(audio_path, "wb") as f:
                f.write(r.content)

        # Transcribe audio with Whisper
        with open(audio_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file
            ).text
        user_message_for_gpt = transcription.lower().replace("reply in voice", "").strip()
        voice_reply = True  # Always reply in voice for audio
    else:
        # Text message
        user_message_for_gpt = Body.lower().replace("reply in voice", "").strip()
        voice_reply = "voice" in Body.lower() or "reply in voice" in Body.lower()

    # Step 3: Prepare GPT messages
    messages = [{"role": "system", "content": system_prompt}]
    for conv in last_messages:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    messages.append({"role": "user", "content": user_message_for_gpt})

    # Step 4: Get GPT response
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            max_tokens=400,
            temperature=0.5
        )
        chatgpt_response = response.choices[0].message.content
        logger.info(f"GPT Response: {chatgpt_response}")
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        chatgpt_response = "Sorry, something went wrong. Please try again later."

    # Step 5: Store conversation in DB
    save_conversation(db, whatsapp_number, user_message_for_gpt, chatgpt_response)

    # Step 6: Send TTS if needed
    if voice_reply:
        try:
            tts_filename = f"{uuid4()}.mp3"
            tts_path = Path("audio") / tts_filename
            with client.audio.speech.with_streaming_response.create(
                model="gpt-4o-mini-tts",
                voice="sage",
                input=chatgpt_response
            ) as tts_resp:
                tts_resp.stream_to_file(tts_path)

            audio_url = f"{NGROK_URL}/audio/{tts_filename}"
            send_message(whatsapp_number, audio_url, is_voice=True)
        except Exception as e:
            logger.error(f"TTS generation error: {e}")
            send_message(whatsapp_number, chatgpt_response)
    else:
        send_message(whatsapp_number, chatgpt_response)

    return ""
