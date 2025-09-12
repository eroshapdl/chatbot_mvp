"""
Facebook Messenger Setup Script
Run this after setting up your Facebook App to configure the bot properly
"""

import requests
from decouple import config

FACEBOOK_PAGE_ACCESS_TOKEN = config("FACEBOOK_PAGE_ACCESS_TOKEN")

def setup_facebook_messenger():
    """Complete setup for Facebook Messenger bot"""
    
    print("Setting up Facebook Messenger bot...")
    
    # 1. Set up greeting message
    setup_greeting()
    
    # 2. Set up get started button
    setup_get_started()
    
    # 3. Set up persistent menu (optional)
    setup_persistent_menu()
    
    print("Facebook Messenger setup completed!")

def setup_greeting():
    """Set up greeting message"""
    url = f"https://graph.facebook.com/v18.0/me/messenger_profile?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    
    payload = {
        "greeting": [
            {
                "locale": "default",
                "text": "Hello! I'm Dr. Emily, your AI medical assistant. I'm here to help answer your health questions and provide medical guidance. Type 'Hello' to start our conversation!"
            }
        ]
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        print("✅ Greeting message set up successfully")
    else:
        print(f"❌ Error setting up greeting: {response.text}")

def setup_get_started():
    """Set up Get Started button"""
    url = f"https://graph.facebook.com/v18.0/me/messenger_profile?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    
    payload = {
        "get_started": {
            "payload": "GET_STARTED"
        }
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        print("✅ Get Started button set up successfully")
    else:
        print(f"❌ Error setting up Get Started button: {response.text}")

def setup_persistent_menu():
    """Set up persistent menu"""
    url = f"https://graph.facebook.com/v18.0/me/messenger_profile?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    
    payload = {
        "persistent_menu": [
            {
                "locale": "default",
                "composer_input_disabled": False,
                "call_to_actions": [
                    {
                        "type": "postback",
                        "title": "New Consultation",
                        "payload": "NEW_CONSULTATION"
                    },
                    {
                        "type": "postback",
                        "title": "Emergency Info",
                        "payload": "EMERGENCY_INFO"
                    },
                    {
                        "type": "web_url",
                        "title": "Health Tips",
                        "url": "https://www.who.int/health-topics"
                    }
                ]
            }
        ]
    }
    
    response = requests.post(url, json=payload)
    
    if response.status_code == 200:
        print("✅ Persistent menu set up successfully")
    else:
        print(f"❌ Error setting up persistent menu: {response.text}")

def test_webhook():
    """Test webhook configuration"""
    print("\n🔍 Testing webhook configuration...")
    print("Make sure your ngrok is running and webhook is configured at:")
    print("https://eb1ee012f8d9.ngrok-free.app/facebook/webhook")
    print("\nTo test:")
    print("1. Go to your Facebook Page")
    print("2. Send a message to test the bot")
    print("3. Check your terminal for webhook logs")

def get_page_info():
    """Get information about the Facebook page"""
    url = f"https://graph.facebook.com/v18.0/me?access_token={FACEBOOK_PAGE_ACCESS_TOKEN}"
    
    response = requests.get(url)
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n📄 Page Information:")
        print(f"Page Name: {data.get('name', 'N/A')}")
        print(f"Page ID: {data.get('id', 'N/A')}")
        print(f"Category: {data.get('category', 'N/A')}")
    else:
        print(f"❌ Error getting page info: {response.text}")

if __name__ == "__main__":
    try:
        get_page_info()
        setup_facebook_messenger()
        test_webhook()
    except Exception as e:
        print(f"❌ Error during setup: {e}")
        print("Make sure your FACEBOOK_PAGE_ACCESS_TOKEN is set correctly in .env file")