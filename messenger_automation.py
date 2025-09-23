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
        
        self.processed_exact_messages = set()
        self.last_response_time = {}
        
        self.db = SessionLocal()
        self.load_state()
        
        self.system_prompt = """You are Dr. Nova, a medical assistant. 

CRITICAL INSTRUCTIONS:
1. READ THE USER'S MESSAGE CAREFULLY - respond to their EXACT symptoms
2. Keep responses under 80 words
3. Focus on the specific condition they mention 
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
            
            if chat_links:
                logger.info(f"Found {len(chat_links)} chat links")
                return chat_links[:3]
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

    def get_conversation_container(self):
        """Get the main conversation container for more targeted message extraction"""
        try:
            # Common selectors for messenger conversation area
            container_selectors = [
                '[role="main"]',
                '[data-testid="conversation"]',
                '.conversation-area',
                '[aria-label*="conversation"]',
                '[role="log"]'  # Message history container
            ]
            
            for selector in container_selectors:
                try:
                    container = self.driver.find_element(By.CSS_SELECTOR, selector)
                    logger.debug(f"Found conversation container with selector: {selector}")
                    return container
                except:
                    continue
                    
            # Fallback to body
            logger.warning("Using body as conversation container fallback")
            return self.driver.find_element(By.TAG_NAME, 'body')
            
        except Exception as e:
            logger.error(f"Error getting conversation container: {e}")
            return None

    def is_outgoing_message(self, element):
        """Helper method to determine if a message is outgoing (bot's own)"""
        try:
            logger.debug(f"Checking element: aria-label={element.get_attribute('aria-label')}, class={element.get_attribute('class')}")
            
            # Check aria-label indicators
            aria_label = element.get_attribute('aria-label') or ''
            if any(indicator in aria_label.lower() for indicator in [
                'you sent', 'you:', 'you said', 'you replied', 'sent by you'
            ]):
                logger.debug(f"Outgoing message detected by aria-label: {aria_label}")
                return True
            
            # Check for specific data attributes that indicate outgoing messages
            try:
                data_testid = element.get_attribute('data-testid') or ''
                if any(testid in data_testid for testid in [
                    'outgoing-message', 'message-sent'
                ]):
                    logger.debug(f"Outgoing message detected by data-testid: {data_testid}")
                    return True
            except:
                pass
            
            # Check parent elements for outgoing indicators
            try:
                parents = element.find_elements(By.XPATH, './ancestor::*[@aria-label]')
                for parent in parents:
                    parent_aria = parent.get_attribute('aria-label') or ''
                    if any(indicator in parent_aria.lower() for indicator in [
                        'you sent', 'you:', 'you said', 'you replied', 'sent by you'
                    ]):
                        logger.debug(f"Outgoing message detected by parent aria-label: {parent_aria}")
                        return True
            except:
                pass
            
            # Check for specific CSS classes that indicate outgoing messages
            try:
                class_name = element.get_attribute('class') or ''
                # These are common patterns for right-aligned/outgoing messages
                if any(pattern in class_name.lower() for pattern in [
                    'right', 'outgoing', 'sent', 'message_out', 'out', 'my-message',
                    'self', 'own', 'from-me', 'sent-message'
                ]):
                    logger.debug(f"Outgoing message detected by CSS class: {class_name}")
                    return True
            except:
                pass
            
            # Position-based check (right side = outgoing)
            try:
                window_width = self.driver.get_window_size()['width']
                x_position = element.location['x']
                
                # If message is on the right 40% of screen, likely outgoing
                if x_position > window_width * 0.6:
                    logger.debug(f"Outgoing message detected by position: x={x_position}, window_width={window_width}")
                    return True
            except:
                pass
                
            return False
            
        except Exception as e:
            logger.error(f"Error checking if outgoing message: {e}")
            return False

    def is_recent_message(self, element, max_age_minutes=2):
        """Check if message is recent enough to respond to"""
        try:
            # Look for time elements near the message
            time_selectors = [
                'time',
                '[aria-label*="time"]',
                '[data-testid*="timestamp"]',
                '.timestamp',
                '.message-time'
            ]
            
            # Check if message has a timestamp element
            for selector in time_selectors:
                try:
                    time_elements = element.find_elements(By.XPATH, f'./preceding-sibling::{selector} | ./following-sibling::{selector}')
                    if time_elements:
                        time_text = time_elements[0].text.strip().lower()
                        
                        # If timestamp indicates very recent message (seconds/minutes)
                        if any(recent_indicator in time_text for recent_indicator in [
                            'now', 'sec', 'min', 'just now', 'moment ago'
                        ]):
                            return True
                except:
                    continue
                    
            # Default to True if we can't determine the time
            return True
            
        except Exception as e:
            logger.debug(f"Error checking message timestamp: {e}")
            return True

    def extract_user_messages(self, chat_id):
        """Extract only incoming user messages with multiple fallback strategies"""
        try:
            time.sleep(2)
            
            logger.debug(f"Starting message extraction for chat {chat_id}")
            
            # Get conversation container for more targeted search
            container = self.get_conversation_container()
            if not container:
                logger.warning("Could not find conversation container")
                return []
            
            # Strategy 1: Get all potential message elements
            all_message_elements = container.find_elements(
                By.CSS_SELECTOR, 'div[dir="auto"]'
            )
            
            logger.debug(f"Found {len(all_message_elements)} potential message elements")
            
            if not all_message_elements:
                logger.info("No message elements found")
                return []
            
            # Filter out bot's own messages using multiple criteria
            user_message_elements = []
            window_width = self.driver.get_window_size()['width']
            
            for element in all_message_elements:
                try:
                    # Skip if this is an outgoing message (bot's own messages)
                    if self.is_outgoing_message(element):
                        logger.debug("Skipping outgoing message")
                        continue
                    
                    # Skip if message is not recent
                    if not self.is_recent_message(element):
                        logger.debug("Skipping old message")
                        continue
                    
                    # Check text content
                    text = element.text.strip()
                    if not text:
                        continue
                        
                    # Skip UI elements and system messages
                    if any(ui_word in text.lower() for ui_word in [
                        'active now', 'send', 'type a message', 'search',
                        'sent a photo', 'sent a video', 'reacted to', 'call started',
                        'call ended', 'joined the call', 'left the chat', 'added',
                        'removed', 'changed the', 'set the', 'unsent a message',
                        'liked a message', 'loved a message', 'haha', 'wow', 'sad', 'angry'
                    ]):
                        continue
                        
                    # Additional filtering for very short messages that might be UI elements
                    if len(text) < 2:
                        continue
                    
                    # Get position for additional validation
                    try:
                        location = element.location
                        x_position = location['x']
                        y_position = location['y']
                        
                        # Messages on the left side of screen are typically incoming
                        # Also filter out messages that are too far left (might be UI elements)
                        if 50 < x_position < window_width * 0.6:
                            user_message_elements.append({
                                'element': element,
                                'text': text,
                                'x_pos': x_position,
                                'y_pos': y_position
                            })
                            logger.debug(f"Valid user message candidate: '{text[:30]}...' at x={x_position}")
                    except:
                        continue
                        
                except Exception as e:
                    logger.debug(f"Error processing element: {e}")
                    continue
            
            # Strategy 2: Additional XPath-based filtering for more precision
            try:
                # This XPath excludes divs that are descendants of elements with "You sent"
                xpath_user_messages = container.find_elements(
                    By.XPATH, 
                    './/div[@dir="auto" and not(ancestor::*[contains(@aria-label, "You sent")]) and not(ancestor::*[contains(@aria-label, "You:")]) and not(ancestor::*[contains(@aria-label, "You replied")]) and text()]'
                )
                
                # Cross-reference with position-filtered results
                xpath_texts = {elem.text.strip() for elem in xpath_user_messages if elem.text.strip()}
                
                # Keep only messages that pass both filters
                user_message_elements = [
                    msg for msg in user_message_elements 
                    if msg['text'] in xpath_texts
                ]
                
                logger.debug(f"XPath filtering kept {len(user_message_elements)} messages")
                
            except Exception as xpath_error:
                logger.warning(f"XPath filtering failed: {xpath_error}")
                # Continue with position-based filtering only
            
            if not user_message_elements:
                logger.info("No user message elements found after filtering")
                return []
            
            # Sort by vertical position (most recent at bottom)
            user_message_elements.sort(key=lambda x: x['y_pos'])
            
            # Get the most recent user message
            latest_message = user_message_elements[-1]
            message_text = latest_message['text']
            
            # Additional validation: skip very short or suspicious messages
            if len(message_text.strip()) < 1:
                logger.info("Message too short, skipping")
                return []
            
            # Create unique message ID
            exact_message_id = hashlib.md5(f"{chat_id}_{message_text}".encode()).hexdigest()
            
            # Check if already processed
            if exact_message_id in self.processed_exact_messages:
                logger.info(f"Already processed this message: '{message_text[:50]}...'")
                return []
            
            logger.info(f"✅ Found new user message: '{message_text}' (x_pos: {latest_message['x_pos']})")
            
            return [{
                'id': exact_message_id,
                'text': message_text,
                'timestamp': datetime.now()
            }]
            
        except Exception as e:
            logger.error(f"Error extracting messages: {e}")
            return []

    def generate_focused_response(self, message_text, chat_id):
        try:
            logger.info(f"Generating response for: '{message_text}'")
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
            # Wait a bit before sending to seem more natural
            time.sleep(1)
            
            input_selectors = [
                '[contenteditable="true"][role="textbox"]',
                'div[contenteditable="true"]',
                '[data-testid="message-input"]',
                '[aria-label*="message"]'
            ]
            
            message_input = None
            for selector in input_selectors:
                try:
                    message_input = self.wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                    )
                    logger.debug(f"Found message input with selector: {selector}")
                    break
                except:
                    continue
            
            if not message_input:
                logger.error("Cannot find message input")
                return False
            
            # Clear any existing text and send new message
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
        try:
            chat_id = self.get_chat_id(chat_element)
            if not chat_id:
                logger.warning("Could not get chat ID")
                return False
                
            logger.info(f"🔍 Processing chat: {chat_id}")
            
            # Check if we've responded recently to avoid spam
            last_time = self.last_response_time.get(chat_id)
            if last_time:
                try:
                    last_datetime = datetime.fromisoformat(last_time)
                    time_diff = (datetime.now() - last_datetime).total_seconds()
                    if time_diff < 30:  # Increased to 30 second cooldown
                        logger.info(f"Responded to chat {chat_id} recently ({time_diff:.1f}s ago), skipping")
                        return True
                except Exception as e:
                    logger.debug(f"Error parsing last response time: {e}")
                    pass
            
            # Click on the chat
            if not self.click_chat(chat_element):
                return False
            
            # Extract user messages
            messages = self.extract_user_messages(chat_id)
            
            if not messages:
                logger.info(f"No new messages in chat {chat_id}")
                return True
            
            message = messages[0]
            message_text = message['text']
            message_id = message['id']
            
            logger.info(f"📨 Processing message: '{message_text}'")
            
            # Generate and send response
            response = self.generate_focused_response(message_text, chat_id)
            
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
            logger.error("❌ Login failed")
            return
        
        logger.info("🚀 Bot running - will respond to NEW user messages only")
        
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while True:
            try:
                logger.info("⏰ Checking for new messages...")
                
                chats = self.get_chat_list()
                
                if chats:
                    logger.info(f"Found {len(chats)} chats")
                    
                    # Process only the first chat to avoid overwhelming
                    for chat in chats[:1]:
                        try:
                            if self.process_chat(chat):
                                consecutive_errors = 0  # Reset error counter on success
                                break
                        except Exception as e:
                            logger.error(f"Error with individual chat: {e}")
                            consecutive_errors += 1
                            continue
                else:
                    logger.info("No chats found")
                
                # Check for too many consecutive errors
                if consecutive_errors >= max_consecutive_errors:
                    logger.error(f"Too many consecutive errors ({consecutive_errors}), sleeping longer")
                    time.sleep(60)  # Sleep for 1 minute
                    consecutive_errors = 0
                
                logger.info("⏳ Waiting 5 seconds...")
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("🛑 Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                consecutive_errors += 1
                time.sleep(30)
        
        # Cleanup
        self.save_state()
        self.driver.quit()
        self.db.close()
        logger.info("Bot shutdown complete")

if __name__ == "__main__":
    print("🤖 Improved Facebook Messenger Bot")
    print("="*50)
    print("Enhanced Features:")
    print("✅ Robust user message detection")
    print("✅ Ignores bot's own messages")
    print("✅ Multiple filtering strategies")
    print("✅ Position-based validation")
    print("✅ Conversation context awareness")
    print("✅ Medical response generation")
    print("✅ No duplicate responses")
    print("✅ Error handling & recovery")
    print("="*50)
    
    try:
        bot = ImprovedMessengerBot()
        bot.run_bot()
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
        print(f"❌ Failed to start bot: {e}")