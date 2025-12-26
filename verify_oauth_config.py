
import os
from config import Config

# Force reload of env vars if needed, but Config should have them now
print("Checking Google OAuth Configuration...")

client_id = Config.GOOGLE_CLIENT_ID
client_secret = Config.GOOGLE_CLIENT_SECRET

if client_id and client_secret:
    print("✅ GOOGLE_CLIENT_ID is set.")
    print(f"   Value: {client_id[:10]}...{client_id[-10:]}")
    print("✅ GOOGLE_CLIENT_SECRET is set.")
    print(f"   Value: {client_secret[:3]}...{client_secret[-3:]}")
    
    # Also check if they are in os.environ for authlib
    if os.environ.get('GOOGLE_CLIENT_ID') == client_id:
         print("✅ GOOGLE_CLIENT_ID is present in os.environ")
    else:
         print("❌ GOOGLE_CLIENT_ID NOT synced to os.environ (authlib might fail)")
         
    if os.environ.get('GOOGLE_CLIENT_SECRET') == client_secret:
         print("✅ GOOGLE_CLIENT_SECRET is present in os.environ")
    else:
         print("❌ GOOGLE_CLIENT_SECRET NOT synced to os.environ (authlib might fail)")

else:
    print("❌ Configuration Mismatch!")
    print(f"   GOOGLE_CLIENT_ID: {client_id}")
    print(f"   GOOGLE_CLIENT_SECRET: {client_secret}")
