# test_env.py
from decouple import config

print("TWILIO_ACCOUNT_SID:", config("TWILIO_ACCOUNT_SID"))
print("TWILIO_AUTH_TOKEN:", config("TWILIO_AUTH_TOKEN"))
print("TWILIO_NUMBER:", config("TWILIO_NUMBER"))