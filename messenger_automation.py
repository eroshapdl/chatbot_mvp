from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import time
import openai
from datetime import datetime, timedelta
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

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('improved_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
    __tablename__ = "conversations"
    
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    sender = Column(String, index=True)
    message = Column(Text, nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

Base.metadata.create_all(engine)

class ImprovedMessengerBot:
    def __init__(self):
        self.setup_chrome()
        self.openai_client = openai.OpenAI(api_key=config("OPENAI_API_KEY"))
        
        # Simple tracking - only track exact message hashes
        self.processed_exact_messages = set()
        self.last_response_time = {}
        
        self.db = SessionLocal()
        self.load_state()
        
        # Improved system prompt for accurate responses
        self.system_prompt = """You are Dr. Nova, a medical assistant. 

CRITICAL INSTRUCTIONS:
1. READ THE USER'S MESSAGE CAREFULLY - respond to their EXACT symptoms
2. Keep responses under 80 words
3. Focus on the specific condition they mention (ear pain, headache, etc.)
4. Suggest appropriate over-the-counter remedies for that specific condition
5. Always recommend seeing a doctor for persistent or severe symptoms



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
        try:
            if os.path.exists('bot_state.json'):
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
            
            print("\n" + "="*5)
            print("LOGIN TO MESSENGER")
            print("="*50)
            print("1. Log in to Facebook/Messenger")
            print("2. Make sure chat list is visible")
            print("3. Press Enter when ready...")
            print("="*5)
            input()
            
            return True
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    def get_chat_list(self):
        try:
            # Look for chat links
            time.sleep(2)
            chat_links = self.driver.find_elements(By.CSS_SELECTOR, 'a[href*="/t/"]')
            
            if chat_links:
                logger.info(f"Found {len(chat_links)} chat links")
                return chat_links[:3]  # Process max 3 chats
            else:
                logger.info("No chat links found")
                return []
                
        except Exception as e:
            logger.error(f"Error getting chats: {e}")
            return []
    
    def get_chat_id(self, chat_element):
        try:
            href = chat_element.get_attribute('href')
            if '/t/' in href:
                return href.split('/t/')[1].split('/')[0]
            return None
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
    
    def extract_user_messages(self, chat_id):
        """Extract only the most recent user messages"""
        try:
            time.sleep(2)
            
            # Get the current page HTML to analyze the conversation
            page_source = self.driver.page_source
            
            # Look for message elements more precisely
            message_elements = self.driver.find_elements(By.CSS_SELECTOR, 'div[dir="auto"]')
            
            if not message_elements:
                logger.info("No message elements found")
                return []
            
            # Get recent message elements
            recent_elements = message_elements[-20:]  # Last 20 elements
            
            potential_messages = []
            window_width = self.driver.get_window_size()['width']
            
            for element in recent_elements:
                try:
                    text = element.text.strip()
                    
                    # Skip empty or very short texts
                    if not text or len(text) < 4:
                        continue
                    
                    # Skip UI elements
                    if any(ui_word in text.lower() for ui_word in [
                        'active now', 'send', 'type a message', 'search',
                        'sent a photo', 'sent a video', 'reacted to'
                    ]):
                        continue
                    
                    # Check if it's from the user (left side typically)
                    location = element.location
                    is_from_user = location['x'] < window_width * 0.6
                    
                    if is_from_user:
                        potential_messages.append({
                            'text': text,
                            'location': location,
                            'y_pos': location['y']
                        })
                        
                except Exception:
                    continue
            
            # Sort by vertical position and get the most recent
            potential_messages.sort(key=lambda x: x['y_pos'])
            
            # Return only the last message (most recent)
            if potential_messages:
                latest_message = potential_messages[-1]
                message_text = latest_message['text']
                
                # Create unique ID for this exact message
                exact_message_id = hashlib.md5(f"{chat_id}_{message_text}".encode()).hexdigest()
                
                # Check if we've already processed this exact message
                if exact_message_id in self.processed_exact_messages:
                    logger.info(f"Already processed this message: '{message_text[:50]}...'")
                    return []
                
                logger.info(f"Found new user message: '{message_text}'")
                return [{
                    'id': exact_message_id,
                    'text': message_text,
                    'timestamp': datetime.now()
                }]
            
            return []
            
        except Exception as e:
            logger.error(f"Error extracting messages: {e}")
            return []
    
    def generate_focused_response(self, message_text, chat_id):
        """Generate response focused on the exact user message"""
        try:
            logger.info(f"Generating response for: '{message_text}'")
            
            # Don't use old conversation context - focus only on current message
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
            
            # Save to database
            conversation = Conversation(
                sender=chat_id,
                message=message_text,
                response=ai_response
            )
            self.db.add(conversation)
            self.db.commit()
            
            logger.info(f"Generated response: '{ai_response}'")
            return ai_response
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return "I'm having trouble right now. For medical concerns, please consult a healthcare professional."
    
    def send_message(self, message_text):
        try:
            # Find message input
            input_selectors = [
                '[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
                '[data-testid="message-input"]'
            ]
            
            message_input = None
            for selector in input_selectors:
                try:
                    message_input = self.wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    break
                except:
                    continue
            
            if not message_input:
                logger.error("Cannot find message input")
                return False
            
            # Send message
            message_input.click()
            time.sleep(0.5)
            message_input.send_keys(Keys.CONTROL + "a")
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
        try:
            chat_id = self.get_chat_id(chat_element)
            if not chat_id:
                return False
            
            logger.info(f"🔍 Processing chat: {chat_id}")
            
            # Check if we responded to this chat recently (within 5 minutes)
            last_time = self.last_response_time.get(chat_id)
            if last_time:
                try:
                    last_datetime = datetime.fromisoformat(last_time)
                    if (datetime.now() - last_datetime).total_seconds() < 10:  # 5 minutes
                        logger.info(f"Responded to chat {chat_id} recently, skipping")
                        return True
                except:
                    pass
            
            if not self.click_chat(chat_element):
                return False
            
            # Extract new messages
            messages = self.extract_user_messages(chat_id)
            
            if not messages:
                logger.info(f"No new messages in chat {chat_id}")
                return True
            
            # Process the new message
            message = messages[0]  # Should be only one
            message_text = message['text']
            message_id = message['id']
            
            logger.info(f"📨 Processing: '{message_text}'")
            
            # Generate response
            response = self.generate_focused_response(message_text, chat_id)
            
            # Send response
            if self.send_message(response):
                # Mark as processed
                self.processed_exact_messages.add(message_id)
                self.last_response_time[chat_id] = datetime.now().isoformat()
                self.save_state()
                logger.info("✅ Message processed successfully")
                return True
            else:
                logger.error("❌ Failed to send response")
                return False
            
        except Exception as e:
            logger.error(f"Error processing chat: {e}")
            return False
    
    def run_bot(self):
        logger.info("🤖 Starting Improved Messenger Bot")
        
        if not self.login_to_messenger():
            logger.error("Login failed")
            return
        
        logger.info("🚀 Bot running - will respond to NEW messages only")
        
        while True:
            try:
                logger.info("⏰ Checking for new messages...")
                
                chats = self.get_chat_list()
                
                if chats:
                    logger.info(f"Found {len(chats)} chats")
                    
                    # Process one chat per cycle to avoid overwhelming
                    for chat in chats[:1]:  # Only first chat
                        try:
                            if self.process_chat(chat):
                                break  # Stop after processing one message
                        except Exception as e:
                            logger.error(f"Error with chat: {e}")
                            continue
                else:
                    logger.info("No chats found")
                
                # Wait before next check
                logger.info("⏳ Waiting 5 seconds...")
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(30)
        
        self.save_state()
        self.driver.quit()
        self.db.close()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    print("🤖 Improved Message Detection Bot")
    print("This version focuses on:")
    print("- Accurate message detection")
    print("- Relevant medical responses")
    print("- No duplicate responses")
    print("=" * 50)
    
    try:
        bot = ImprovedMessengerBot()
        bot.run_bot()
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")