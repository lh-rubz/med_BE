import requests
import os
import sys

# Read from environment variables (User's preferred method)
http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
PROXY_URL = https_proxy or http_proxy

if not PROXY_URL:
    print("⚠️  No proxy found in environment variables (http_proxy/https_proxy).")
    print("   Please run 'export http_proxy=...' first.")
    # Fallback for testing if user forgets
    # PROXY_URL = "http://213.244.124.19:3128" 

print(f"🔍 Testing connectivity to {TARGET_URL}")
print(f"ℹ️  Using Proxy: {PROXY_URL}")

proxies = {
    "http": PROXY_URL,
    "https": PROXY_URL,
}

try:
    print("\n1️⃣  Testing simple connection...")
    response = requests.get("https://api.brevo.com", proxies=proxies, timeout=10)
    print(f"✅ Connection successful! Status Code: {response.status_code}")
except Exception as e:
    print(f"❌ Connection failed: {e}")

try:
    print("\n2️⃣  Testing API endpoint (expecting 401 or 405)...")
    # We expect a 401 (Unauthorized) or 405 (Method Not Allowed) if we reach the server
    # If we get a timeout or connection error, the proxy is failing
    response = requests.get(TARGET_URL, proxies=proxies, timeout=10)
    print(f"✅ API Endpoint reachable! Status Code: {response.status_code}")
    if response.status_code in [401, 405, 200]:
        print("   (This is good - it means we reached Brevo)")
    else:
        print("   (Unexpected status code, but at least we got a response)")
except Exception as e:
    print(f"❌ API Endpoint check failed: {e}")
