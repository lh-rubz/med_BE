import os
from datetime import timedelta
from dotenv import load_dotenv
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from openai import OpenAI

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# Load environment variables from .env file
load_dotenv()

# Google Configuration
# Credentials should be set in environment variables
# os.environ['GOOGLE_CLIENT_ID'] = '...'
# os.environ['GOOGLE_CLIENT_SECRET'] = '...'

# Configure NO_PROXY to exclude localhost from proxy (important for local VLM server)
no_proxy = os.environ.get('NO_PROXY', '')
no_proxy_list = [item.strip() for item in no_proxy.split(',') if item.strip()]
no_proxy_list.extend(['localhost', '127.0.0.1', '0.0.0.0', '::1', 'localhost:11434', '127.0.0.1:11434'])
no_proxy_list.extend(['localhost', '127.0.0.1', '0.0.0.0', '::1', 'localhost:11434', '127.0.0.1:11434'])
# Set both uppercase and lowercase to ensure compatibility
os.environ['NO_PROXY'] = ','.join(set(no_proxy_list))
os.environ['no_proxy'] = os.environ['NO_PROXY']

# Temporarily unset proxy env vars before creating httpx client
_original_proxy_vars = {}
for var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    if var in os.environ:
        _original_proxy_vars[var] = os.environ.pop(var)


class Config:
    # Database configuration
    DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:user@localhost/meddb')
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Secret keys
    SECRET_KEY = os.getenv('SECRET_KEY', 'MedicalApp@2025SecureKey123')
    JWT_SECRET_KEY = SECRET_KEY
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=1)
    JWT_TOKEN_LOCATION = ['headers', 'query_string']
    JWT_QUERY_STRING_NAME = 'token'
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'
    
    # Email configuration for Brevo SMTP
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp-relay.brevo.com')
    MAIL_PORT = int(os.getenv('MAIL_PORT', 587))
    MAIL_USE_TLS = os.getenv('MAIL_USE_TLS', 'True').lower() == 'true'
    MAIL_USE_SSL = os.getenv('MAIL_USE_SSL', 'False').lower() == 'true'
    MAIL_USERNAME = os.getenv('MAIL_USERNAME')
    MAIL_PASSWORD = os.getenv('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER')
    
    # Brevo API configuration
    BREVO_API_KEY = os.getenv('BREVO_API_KEY')
    SENDER_EMAIL = os.getenv('SENDER_EMAIL', 'habuelrub@gmail.com')
    SENDER_NAME = os.getenv('SENDER_NAME', 'MediScan')
    
    # Ollama configuration
    OLLAMA_BASE_URL = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
    OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen2.5vl:7b')
    
    # Google OAuth
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')
    
    # WebAuthn Configuration
    RP_ID = os.getenv('RP_ID', '176.119.254.185.nip.io')
    RP_NAME = os.getenv('RP_NAME', 'MediScan')
    # Origin must match exactly what the browser sees
    RP_ORIGIN = os.getenv('RP_ORIGIN', 'http://176.119.254.185.nip.io:8051')
    
    # File upload configuration
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100MB max file size


def send_brevo_email(recipient_email, subject, html_content):
    """Send email using Brevo API"""
    # Validate configuration
    if not Config.BREVO_API_KEY:
        print(f"❌ BREVO_API_KEY is not set in environment variables!")
        return False
    
    if not Config.SENDER_EMAIL:
        print(f"❌ SENDER_EMAIL is not set in environment variables!")
        return False
    
    print(f"\n📧 Attempting to send email:")
    print(f"   From: {Config.SENDER_NAME} <{Config.SENDER_EMAIL}>")
    print(f"   To: {recipient_email}")
    print(f"   Subject: {subject}")
    print(f"   Using Brevo API Key: {Config.BREVO_API_KEY[:20]}...")
    
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key['api-key'] = Config.BREVO_API_KEY
    
    # Explicitly set proxy if available
    http_proxy = os.environ.get('http_proxy') or os.environ.get('HTTP_PROXY')
    https_proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY')
    
    if https_proxy:
        configuration.proxy = https_proxy
        print(f"   Using HTTPS Proxy: {https_proxy}")
    elif http_proxy:
        configuration.proxy = http_proxy
        print(f"   Using HTTP Proxy: {http_proxy}")
    
    # Set timeout (in milliseconds)
    # Note: sib-api-v3-sdk might not expose direct timeout in Configuration, 
    # but we can try to set it on the ApiClient if supported, or rely on socket defaults.
    # However, to be safe, we'll just log clearly before the call.
    
    api_client = sib_api_v3_sdk.ApiClient(configuration)
    api_instance = sib_api_v3_sdk.TransactionalEmailsApi(api_client)

    send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
        sender={"name": Config.SENDER_NAME, "email": Config.SENDER_EMAIL},
        to=[{"email": recipient_email}],
        subject=subject,
        html_content=html_content
    )

    try:
        print("⏳ Sending request to Brevo API...")
        api_response = api_instance.send_transac_email(send_smtp_email)
        print(f"✅ Brevo API Response: {api_response}")
        print(f"✅ Message ID: {api_response.message_id if hasattr(api_response, 'message_id') else 'N/A'}")
        print(f"✅ Email queued successfully! Check your inbox (and spam folder)")
        return True
    except ApiException as e:
        print(f"❌ Exception when calling Brevo API: {e}")
        print(f"   Status: {e.status if hasattr(e, 'status') else 'N/A'}")
        print(f"   Reason: {e.reason if hasattr(e, 'reason') else 'N/A'}")
        print(f"   Response body: {e.body if hasattr(e, 'body') else 'N/A'}")
        return False
    except Exception as e:
        print(f"❌ Network error when sending email: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_ollama_client():
    """Create OpenAI-compatible client pointing at Ollama server"""
    client_kwargs = {
        'base_url': Config.OLLAMA_BASE_URL,
        'api_key': 'not-needed',
    }
    
    if HAS_HTTPX:
        http_client = httpx.Client(timeout=600.0)
        client_kwargs['http_client'] = http_client
    
    client = OpenAI(**client_kwargs)
    return client


# Create the Ollama client
ollama_client = create_ollama_client()

# Restore proxy environment variables
for var, value in _original_proxy_vars.items():
    os.environ[var] = value
