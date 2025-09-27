from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import openai
from datetime import datetime
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, URL
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
from decouple import config
import logging
import hashlib
import json
import os
import re

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('improved_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(_name_)

# Database setup
url = URL.create(
    drivername="postgresql",
    username=config("DB_USER"),
    password=config("DB_PASSWORD"),
    host=config("DB_HOST"),
    port=config("DB_PORT", cast=int),
    database=config("DB_NAME")
)

engine = create_engine(url)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

class Conversation(Base):
    _tablename_ = "conversations"
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    sender = Column(String, index=True)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(engine)

def normalize_text(text):
        return re.sub(r'\W+', '', text.lower().strip())

class ImprovedMessengerBot:
    def _init_(self):
        self.setup_chrome()
        self.openai_client = openai.OpenAI(api_key=config("OPENAI_API_KEY"))
        self.processed_exact_messages = set()
        self.last_response_time = {}
        self.db = SessionLocal()
        self.load_state()
        self.system_prompt = """You are Dr. Nova, a medical assistant. 

CRITICAL INSTRUCTIONS:
1.⁠ ⁠READ THE USER'S MESSAGE CAREFULLY - respond to their EXACT symptoms
2.⁠ ⁠Keep responses under 80 words
3.⁠ ⁠Focus on the specific condition they mention 
4.⁠ ⁠Suggest appropriate over-the-counter remedies for that specific condition
5.⁠ ⁠Always recommend seeing a doctor for persistent or severe symptoms
Always match your advice to their specific symptom."""

    def setup_chrome(self):
        options = Options()
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        self.driver = webdriver.Chrome(options=options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, 15)
        logger.info("Chrome started")

    def load_state(self):
        if os.path.exists('bot_state.json'):
            try:
                with open('bot_state.json', 'r') as f:
                    data = json.load(f)
                    self.processed_exact_messages = set(data.get('processed', []))
                    self.last_response_time = data.get('last_times', {})
                logger.info(f"Loaded {len(self.processed_exact_messages)} processed messages")
            except Exception as e:
                logger.error(f"Error loading state: {e}")

    def save_state(self):
        try:
            data = {
                'processed': list(self.processed_exact_messages),
                'last_times': self.last_response_time
            }
            with open('bot_state.json', 'w') as f:
                json.dump(data, f)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def login_to_messenger(self):
        try:
            logger.info("Opening Messenger...")
            self.driver.get("https://www.messenger.com")
            time.sleep(5)
            print("\n" + "="*50)
            print("LOGIN TO MESSENGER")
            print("="*50)
            print("1. Log in to Facebook/Messenger")
            print("2. Make sure chat list is visible")
            print("3. Press Enter when ready...")
            print("="*50)
            input()
            return True
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def get_chat_list(self):
        try:
            time.sleep(2)
            chat_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/t/"]')
            logger.info(f"Found {len(chat_links)} chat links")
            return chat_links[:3] if chat_links else []
        except Exception as e:
            logger.error(f"Error getting chats: {e}")
            return []

    def get_chat_id(self, chat_element):
        try:
            href = chat_element.get_attribute('href')
            return href.split('/t/')[1].split('/')[0] if '/t/' in href else None
        except:
            return None

    def click_chat(self, chat_element):
        try:
            chat_element.click()
            time.sleep(3)
            return True
        except Exception as e:
            logger.error(f"Error clicking chat: {e}")
            return False

    def get_conversation_container(self):
        selectors = ['[role="main"]', '[data-testid="conversation"]', '.conversation-area', '[aria-label*="conversation"]', '[role="log"]']
        for selector in selectors:
            try:
                return self.driver.find_element(By.CSS_SELECTOR, selector)
            except:
                continue
        return self.driver.find_element(By.TAG_NAME, 'body')

    def is_outgoing_message(self, element):
        try:
            aria_label = (element.get_attribute('aria-label') or '').lower()
            data_testid = (element.get_attribute('data-testid') or '').lower()
            class_name = (element.get_attribute('class') or '').lower()
            x_position = element.location['x']
            window_width = self.driver.get_window_size()['width']

            if any(kw in aria_label for kw in ['you sent', 'you:', 'you said', 'sent by you']):
                return True
            if any(kw in data_testid for kw in ['outgoing-message', 'message-sent']):
                return True
            if any(pattern in class_name for pattern in ['right', 'outgoing', 'sent', 'self', 'own', 'from-me']):
                return True
            if x_position > window_width * 0.6:
                return True
            return False
        except:
            return False

 



    def extract_user_messages(self, chat_id):
        try:
            time.sleep(2)
            container = self.get_conversation_container()
            if not container:
                return []

            all_messages = container.find_elements(By.CSS_SELECTOR, 'div[dir="auto"]')
            user_messages = []

            # Get hashes of previous responses from DB
            previous_responses = set(normalize_text(conv.response) for conv in self.db.query(Conversation).filter(Conversation.sender==chat_id).all())

            for element in all_messages:
                try:
                    text = element.text.strip()
                    if not text or len(text) < 2:
                        continue

                    if self.is_outgoing_message(element):
                        continue

                    if any(ui_word in text.lower() for ui_word in [
                        'active now', 'send', 'type a message', 'sent a photo', 'sent a video', 'reacted to'
                    ]):
                        continue

                    if normalize_text(text) in previous_responses:
                        continue  # Already replied to this text

                    x_position = element.location['x']
                    window_width = self.driver.get_window_size()['width']
                    if 50 < x_position < window_width * 0.6:
                        user_messages.append({
                            'element': element,
                            'text': text,
                            'x_pos': x_position,
                            'y_pos': element.location['y']
                        })
                except:
                    continue

            if not user_messages:
                return []

            user_messages.sort(key=lambda x: x['y_pos'])
            latest_message = user_messages[-1]
            text = latest_message['text']
            message_id = hashlib.md5(f"{chat_id}user{normalize_text(text)}".encode()).hexdigest()

            if message_id in self.processed_exact_messages:
                return []

            logger.info(f"✅ Found new user message: '{text}' (x_pos: {latest_message['x_pos']})")
            return [{'id': message_id, 'text': text, 'timestamp': datetime.now()}]
        except Exception as e:
            logger.error(f"Error extracting messages: {e}")
            return []

        
    def generate_focused_response(self, message_text, chat_id):
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": message_text}
            ]
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                max_tokens=120,
                temperature=0.5
            )
            ai_response = response.choices[0].message.content.strip()

            conversation = Conversation(sender=chat_id, message=message_text, response=ai_response)
            self.db.add(conversation)
            self.db.commit()
            logger.info(f"Generated response: '{ai_response}'")
            return ai_response
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I'm having trouble right now. Please consult a healthcare professional."

    def send_message(self, message_text):
        try:
            time.sleep(1)
            selectors = ['[contenteditable="true"][role="textbox"]', 'div[contenteditable="true"]', '[data-testid="message-input"]', '[aria-label*="message"]']
            message_input = None
            for selector in selectors:
                try:
                    message_input = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    break
                except:
                    continue
            if not message_input:
                logger.error("Cannot find message input")
                return False

            message_input.click()
            time.sleep(0.5)
            message_input.send_keys(Keys.CONTROL + "a")
            time.sleep(0.2)
            message_input.send_keys(message_text)
            time.sleep(1)
            message_input.send_keys(Keys.ENTER)
            time.sleep(2)
            logger.info(f"✅ Sent: '{message_text}'")
            return True
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return False

    def process_chat(self, chat_element):
        chat_id = self.get_chat_id(chat_element)
        if not chat_id:
            return False

        logger.info(f"🔍 Processing chat: {chat_id}")
        last_time = self.last_response_time.get(chat_id)
        if last_time:
            try:
                last_datetime = datetime.fromisoformat(last_time)
                if (datetime.now() - last_datetime).total_seconds() < 30:
                    logger.info(f"Responded to chat {chat_id} recently, skipping")
                    return True
            except:
                pass

        if not self.click_chat(chat_element):
            return False

        messages = self.extract_user_messages(chat_id)
        if not messages:
            return True

        message = messages[0]
        response = self.generate_focused_response(message['text'], chat_id)

        if self.send_message(response):
            self.processed_exact_messages.add(message['id'])
            self.last_response_time[chat_id] = datetime.now().isoformat()
            self.save_state()
            logger.info("✅ Message processed successfully")
            return True
        return False

    def run_bot(self):
        logger.info("🤖 Starting Improved Messenger Bot")
        if not self.login_to_messenger():
            logger.error("❌ Login failed")
            return

        consecutive_errors = 0
        max_consecutive_errors = 5

        while True:
            try:
                chats = self.get_chat_list()
                if chats:
                    for chat in chats[:1]:
                        if self.process_chat(chat):
                            consecutive_errors = 0
                            break
                else:
                    logger.info("No chats found")

                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Too many consecutive errors ({consecutive_errors}), sleeping longer")
                    time.sleep(60)
                    consecutive_errors = 0

                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                consecutive_errors += 1
                time.sleep(30)

        self.save_state()
        self.driver.quit()
        self.db.close()
        logger.info("Bot shutdown complete")


if _name_ == "_main_":
    print("🤖 Improved Facebook Messenger Bot")
    print("="*50)
    bot = ImprovedMessengerBot()
    bot.run_bot()

