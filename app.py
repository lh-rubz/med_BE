from flask import Flask
from flask_restx import Api
from flask_jwt_extended import JWTManager
from flask_mail import Mail

from config import Config
from models import db
from routes import auth_ns, user_ns, vlm_ns, reports_ns

# Create Flask app
app = Flask(__name__)

# Load configuration
app.config.from_object(Config)

# Initialize extensions
db.init_app(app)
jwt = JWTManager(app)
mail = Mail(app)

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
    security='Bearer Auth'
)

# Register namespaces (routes)
api.add_namespace(auth_ns, path='/auth')
api.add_namespace(user_ns, path='/users')
api.add_namespace(vlm_ns, path='/vlm')
api.add_namespace(reports_ns, path='/reports')


def init_db():
    """Initialize the database"""
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully!")
        except Exception as e:
            print(f"Database initialization warning: {e}")
            print("App will run in read-only mode. Please verify PostgreSQL connection.")


if __name__ == '__main__':
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
