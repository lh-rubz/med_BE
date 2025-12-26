from flask import Flask
from flask_restx import Api
from flask_jwt_extended import JWTManager
from flask_mail import Mail
from flask_cors import CORS
import os

from config import Config
from models import db
from models import db
from routes.auth_routes import auth_ns
from routes.user_routes import user_ns
from routes.vlm_routes import vlm_ns
from routes.report_routes import reports_ns
from routes.auth_routes import oauth
from routes.webauthn_routes import webauthn_ns
from utils.medical_mappings import seed_synonyms

# Create Flask app
app = Flask(__name__)

# Load configuration
app.config.from_object(Config)

# Enable CORS for all routes and origins
CORS(app, resources={r"/*": {"origins": "*"}})

# Ensure upload folder exists
os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)
mail = Mail(app)
oauth.init_app(app)


# Serve the test upload HTML page
@app.route('/test-upload')
def test_upload():
    """Serve the test upload HTML page"""
    return app.send_static_file('test_upload.html')


# Initialize API with Swagger documentation
api = Api(
    app,
    version="1.0",
    title="Medical Application API",
    description="API for Medical Application with secure user management",
    doc="/swagger",
    authorizations={
        'Bearer Auth': {
            'type': 'apiKey',
            'in': 'header',
            'name': 'Authorization',
            'description': 'JWT Bearer token. Example: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
        }
    },
    security='Bearer Auth',
    # Support file uploads in Swagger
    validate=False
)

# Register namespaces (routes)
api.add_namespace(auth_ns, path='/auth')
api.add_namespace(webauthn_ns, path='/auth/webauthn')
api.add_namespace(user_ns, path='/users')
api.add_namespace(vlm_ns, path='/vlm')
api.add_namespace(reports_ns, path='/reports')



def print_env_vars():
    """Print relevant environment variables for debugging"""
    import os
    print("\n🔍 Environment Variables Configuration:")
    
    # Database
    db_url = os.getenv('DATABASE_URL', 'Not Set')
    if 'postgresql://' in db_url:
        # Mask password
        try:
            parts = db_url.split('@')
            if len(parts) > 1:
                credentials = parts[0].split(':')
                if len(credentials) > 2:
                    # Mask password part
                    masked_creds = f"{credentials[0]}:{credentials[1]}:****"
                    db_url = f"{masked_creds}@{parts[1]}"
        except:
            pass
    print(f"   - DATABASE_URL: {db_url}")
    
    # Mail
    print(f"   - MAIL_SERVER: {os.getenv('MAIL_SERVER', 'Not Set')}")
    print(f"   - MAIL_PORT: {os.getenv('MAIL_PORT', 'Not Set')}")
    print(f"   - MAIL_USE_TLS: {os.getenv('MAIL_USE_TLS', 'Not Set')}")
    print(f"   - MAIL_USE_SSL: {os.getenv('MAIL_USE_SSL', 'Not Set')}")
    
    # Brevo
    api_key = os.getenv('BREVO_API_KEY', 'Not Set')
    if len(api_key) > 10:
        api_key = f"{api_key[:5]}...{api_key[-5:]}"
    print(f"   - BREVO_API_KEY: {api_key}")
    
    # Ollama
    print(f"   - OLLAMA_BASE_URL: {os.getenv('OLLAMA_BASE_URL', 'Not Set')}")
    
    # Proxy
    print(f"   - http_proxy: {os.getenv('http_proxy', 'Not Set')}")
    print(f"   - https_proxy: {os.getenv('https_proxy', 'Not Set')}")
    print(f"   - no_proxy: {os.getenv('no_proxy', 'Not Set')}")
    print("-" * 50 + "\n")


def init_db():
    """Initialize the database"""
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully!")
            
            # Seed medical synonyms
            from utils.medical_mappings import seed_synonyms
            seed_synonyms()
        except Exception as e:
            print(f"Database initialization warning: {e}")
            print("App will run in read-only mode. Please verify PostgreSQL connection.")


if __name__ == '__main__':
    # Print environment variables
    print_env_vars()

    # Initialize the database
    init_db()
    
    print("\n✅ Starting Medical Application API...")
    print("📚 Swagger documentation available at: http://localhost:8051/swagger")
    print("🔍 API Routes by Namespace:")
    print("\n📋 Authentication (auth/)")
    print("   - POST /auth/register - Register new user")
    print("   - POST /auth/login - Login and get JWT token")
    print("   - POST /auth/verify-email - Verify email with code")
    print("   - POST /auth/resend-verification - Resend verification code")
    print("   - POST /auth/forgot-password - Request password reset")
    print("   - POST /auth/reset-password - Reset password with code")
    print("\n👤 Users (users/)")
    print("   - GET /users/profile - Get user profile (requires JWT)")
    print("   - PUT /users/profile - Update user profile (requires JWT)")
    print("   - DELETE /users/delete-user-testing - Delete user (TESTING ONLY)")
    print("   - POST /users/test-email - Test email sending (TESTING ONLY)")
    print("\n🔬 VLM Operations (vlm/)")
    print("   - POST /vlm/chat - Extract medical report data from image (requires JWT)")
    print("\n📊 Reports Management (reports/)")
    print("   - GET /reports - Get all user reports with extracted data (requires JWT)")
    print("   - GET /reports/<id> - Get a specific report by ID (requires JWT)")
    print("   - DELETE /reports/<id> - Delete a report by ID (requires JWT) [FOR TESTING ONLY]")
    
    app.run(debug=True, host='0.0.0.0', port=8051)
