import os
from openai import OpenAI
from fastapi import FastAPI, Form, Depends, Request
from fastapi.responses import StreamingResponse
from io import BytesIO
from decouple import config
from sqlalchemy.orm import Session

# Internal imports
from models import SessionLocal
from db import save_conversation, get_last_messages
from utils import send_message, logger

# Initialize FastAPI
app = FastAPI()

# OpenAI API Client
client = OpenAI(api_key=config("OPENAI_API_KEY"))

# Doctor system prompt
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
"""

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/")
async def index():
    return {"msg": "working"}

@app.post("/message")
async def reply(request: Request, Body: str = Form(...), db: Session = Depends(get_db)):
    form_data = await request.form()
    whatsapp_number = form_data.get("From", "").split("whatsapp:")[-1].strip()
    logger.info(f"Incoming message from {whatsapp_number}: {Body}")

    # Retrieve last 50 messages for context
    last_messages = get_last_messages(db, whatsapp_number, limit=50)

    # Prepare messages for OpenAI with doctor persona
    messages = [{"role": "system", "content": system_prompt}]
    for conv in last_messages:
        messages.append({"role": "user", "content": conv.message})
        messages.append({"role": "assistant", "content": conv.response})
    messages.append({"role": "user", "content": Body})

    # Call OpenAI GPT-4.1-mini
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=messages,
            max_tokens=250,
            temperature=0.5
        )
        chatgpt_response = response.choices[0].message.content
        logger.info(f"GPT Response: {chatgpt_response}")
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        chatgpt_response = "Sorry, something went wrong. Please try again later."

    # Store conversation in DB
    save_conversation(db, whatsapp_number, Body, chatgpt_response)

    # Send message via Twilio
    send_message(whatsapp_number, chatgpt_response)
    return ""  # Empty HTTP 200 response
