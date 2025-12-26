from flask import request, url_for, redirect, current_app
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import create_access_token
from datetime import datetime, timedelta, timezone
import secrets
import os
from authlib.integrations.flask_client import OAuth

from models import db, User
from config import send_brevo_email
from email_templates import (
    get_verification_email,
    get_resend_verification_email,
    get_password_reset_email,
    get_password_reset_email_with_link,
    get_password_changed_email
)
from utils.password_validator import validate_password_strength

# Create namespace
auth_ns = Namespace('auth', description='Authentication operations')

# Initialize OAuth
oauth = OAuth()

oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# API Models
register_model = auth_ns.model('Registration', {
    'email': fields.String(required=True, description='User email address'),
    'password': fields.String(required=True, description='User password'),
    'first_name': fields.String(required=True, description='First name'),
    'last_name': fields.String(required=True, description='Last name'),
    'date_of_birth': fields.Date(required=True, description='Date of birth (YYYY-MM-DD)'),
    'phone_number': fields.String(required=True, description='Phone number')
})

login_model = auth_ns.model('Login', {
    'email': fields.String(required=True, description='User email address'),
    'password': fields.String(required=True, description='User password')
})

verify_email_model = auth_ns.model('VerifyEmail', {
    'email': fields.String(required=True, description='User email address'),
    'code': fields.String(required=True, description='6-digit verification code from email')
})

resend_code_model = auth_ns.model('ResendCode', {
    'email': fields.String(required=True, description='User email address')
})

forgot_password_model = auth_ns.model('ForgotPassword', {
    'email': fields.String(required=True, description='User email address')
})

reset_password_model = auth_ns.model('ResetPassword', {
    'email': fields.String(required=True, description='User email address'),
    'code': fields.String(required=True, description='6-digit verification code from email'),
    'new_password': fields.String(required=True, description='New password')
})

verify_reset_code_model = auth_ns.model('VerifyResetCode', {
    'email': fields.String(required=True, description='User email address'),
    'code': fields.String(required=True, description='6-digit reset code from email')
})

change_password_model = auth_ns.model('ChangePassword', {
    'email': fields.String(required=True, description='User email address'),
    'old_password': fields.String(required=True, description='Current password'),
    'new_password': fields.String(required=True, description='New password')
})


@auth_ns.route('/register')
class Register(Resource):
    @auth_ns.expect(register_model)
    def post(self):
        """Register a new user"""
        data = request.json

        if User.query.filter_by(email=data['email']).first():
            return {'message': 'Email already registered'}, 409

        # Validate password strength
        is_valid, error_message = validate_password_strength(data['password'])
        if not is_valid:
            return {'message': error_message}, 400

        try:
            verification_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            
            new_user = User(
                email=data['email'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                date_of_birth=datetime.strptime(str(data['date_of_birth']), '%Y-%m-%d').date(),
                phone_number=data['phone_number'],
                verification_code=verification_code,
                verification_code_expires=datetime.now(timezone.utc) + timedelta(minutes=15),
                email_verified=False
            )
            new_user.set_password(data['password'])
            
            db.session.add(new_user)
            db.session.commit()

            print(f"\n{'='*80}")
            print(f"📧 VERIFICATION CODE for {new_user.email}: {verification_code}")
            print(f"Code expires at: {new_user.verification_code_expires}")
            print(f"{'='*80}\n")

            try:
                html_content = get_verification_email(new_user.first_name, verification_code)
                success = send_brevo_email(
                    recipient_email=new_user.email,
                    subject='Verify Your Email - MediScan',
                    html_content=html_content
                )
                
                if success:
                    print(f"✅ Email sent successfully to {new_user.email}")
                else:
                    print(f"❌ Failed to send email to {new_user.email}")
            except Exception as email_error:
                print(f"❌ Failed to send verification email: {str(email_error)}")

            return {
                'message': 'User registered successfully. Please check your email to verify your account.',
                'verification_required': True
            }, 201
        except Exception as e:
            db.session.rollback()
            return {'message': 'Registration failed', 'error': str(e)}, 400


@auth_ns.route('/login')
class Login(Resource):
    @auth_ns.expect(login_model)
    def post(self):
        """Login and get access token"""
        data = request.json
        user = User.query.filter_by(email=data['email']).first()

        if not user or not user.check_password(data['password']):
            return {'message': 'Invalid email or password'}, 401

        if not user.is_active:
            return {'message': 'Account is deactivated'}, 403

        if not user.email_verified:
            return {
                'message': 'Email not verified. Please verify your email before logging in.',
                'email_verified': False
            }, 403

        access_token = create_access_token(identity=str(user.id))
        access_token = create_access_token(identity=str(user.id))
        return {'access_token': access_token, 'email_verified': True}, 200


@auth_ns.route('/google')
class GoogleLogin(Resource):
    def get(self):
        """Initiate Google OAuth login"""
        # Create the redirect URI
        # We use a hardcoded compatible URI for local dev if needed, or url_for
        # For localhost:8051, url_for should work if SERVER_NAME is set or Host header is present
        # To be safe for the user's setup:
        redirect_uri = url_for('auth_google_callback', _external=True)
        
        # If running behind a proxy or different port mapping, might need adjustment
        # For now, rely on Flask's url_for
        return oauth.google.authorize_redirect(redirect_uri)


@auth_ns.route('/google/callback', endpoint='google_callback')
class GoogleCallback(Resource):
    def get(self):
        """Handle Google OAuth callback"""
        try:
            token = oauth.google.authorize_access_token()
            user_info = token.get('userinfo')
            
            if not user_info:
                return {'message': 'Failed to get user info from Google'}, 400
                
            email = user_info.get('email')
            google_id = user_info.get('sub')
            first_name = user_info.get('given_name', '')
            last_name = user_info.get('family_name', '')
            picture = user_info.get('picture')
            
            # Check if user exists
            user = User.query.filter((User.email == email) | (User.google_id == google_id)).first()
            
            if user:
                # Update existing user
                if not user.google_id:
                    user.google_id = google_id
                
                # Check if we should update profile image
                if picture and (not user.profile_image or user.profile_image == 'default.jpg'):
                    user.profile_image = picture
                    
                # If email wasn't verified, verify it now (trust Google)
                if not user.email_verified:
                    user.email_verified = True
                
                db.session.commit()
            else:
                # Create new user
                user = User(
                    email=email,
                    google_id=google_id,
                    first_name=first_name,
                    last_name=last_name or first_name, # Fallback
                    password=None, # No password for Google users
                    date_of_birth=None, # User can fill later
                    phone_number=None, # User can fill later
                    email_verified=True,
                    profile_image=picture or 'default.jpg'
                )
                db.session.add(user)
                db.session.commit()
            
            # Create access token
            access_token = create_access_token(identity=str(user.id))
            
            # Return token (In a real app, you might redirect to frontend with token)
            return {
                'message': 'Login successful',
                'access_token': access_token,
                'user': {
                    'email': user.email,
                    'first_name': user.first_name,
                    'google_login': True
                }
            }, 200
            
        except Exception as e:
            print(f"Google Auth Error: {str(e)}")
            return {'message': 'Authentication failed', 'error': str(e)}, 400


@auth_ns.route('/verify-email')
class VerifyEmail(Resource):
    @auth_ns.expect(verify_email_model)
    def post(self):
        """Verify user email with 6-digit code"""
        data = request.json
        email = data.get('email')
        code = data.get('code')
        
        if not email or not code:
            return {'message': 'Email and verification code are required'}, 400
        
        if not code.isdigit() or len(code) != 6:
            return {'message': 'Invalid code format. Code must be 6 digits.'}, 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {'message': 'User not found'}, 404
        
        if user.email_verified:
            return {'message': 'Email already verified'}, 200
        
        if not user.verification_code:
            return {'message': 'No verification code found. Please register again.'}, 400
        
        # Ensure verification_code_expires is timezone-aware
        expires = user.verification_code_expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
            
        if expires < datetime.now(timezone.utc):
            return {'message': 'Verification code has expired. Please request a new one.'}, 400
        
        if user.verification_code != code:
            return {'message': 'Invalid verification code'}, 400
        
        try:
            user.email_verified = True
            user.verification_code = None
            user.verification_code_expires = None
            db.session.commit()
            
            return {'message': 'Email verified successfully. You can now log in.'}, 200
        except Exception as e:
            db.session.rollback()
            return {'message': 'Verification failed', 'error': str(e)}, 400


@auth_ns.route('/resend-verification')
class ResendVerification(Resource):
    @auth_ns.expect(resend_code_model)
    def post(self):
        """Resend verification code"""
        data = request.json
        email = data.get('email')
        
        if not email:
            return {'message': 'Email is required'}, 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {'message': 'User not found'}, 404
        
        if user.email_verified:
            return {'message': 'Email already verified'}, 200
        
        try:
            verification_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            user.verification_code = verification_code
            user.verification_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.session.commit()
            
            try:
                html_content = get_resend_verification_email(user.first_name, verification_code)
                success = send_brevo_email(
                    recipient_email=user.email,
                    subject='Verify Your Email - MediScan',
                    html_content=html_content
                )
                
                if not success:
                    print(f"Failed to send verification email to {user.email}")
                    return {'message': 'Failed to send email'}, 500
            except Exception as email_error:
                print(f"Failed to send verification email: {str(email_error)}")
                return {'message': 'Failed to send email', 'error': str(email_error)}, 500
            
            return {'message': 'Verification code sent successfully. Please check your email.'}, 200
        except Exception as e:
            db.session.rollback()
            return {'message': 'Failed to resend verification code', 'error': str(e)}, 400


@auth_ns.route('/forgot-password')
class ForgotPassword(Resource):
    @auth_ns.expect(forgot_password_model)
    def post(self):
        """Request password reset"""
        data = request.json
        email = data.get('email')
        
        if not email:
            return {'message': 'Email is required'}, 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, 200
        
        try:
            # Generate 6-digit reset code
            reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            
            # Store code in the database
            user.reset_code = reset_code
            user.reset_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.session.commit()
            
            print(f"\n{'='*80}")
            print(f"🔑 PASSWORD RESET for {user.email}")
            print(f"   Code: {reset_code}")
            print(f"   Expires at: {user.reset_code_expires}")
            print(f"{'='*80}\n")
            
            try:
                # Use simple email template with code only
                html_content = get_password_reset_email(
                    user.first_name, 
                    reset_code
                )
                success = send_brevo_email(
                    recipient_email=user.email,
                    subject='Password Reset - MediScan',
                    html_content=html_content
                )
                
                if success:
                    print(f"✅ Password reset email sent successfully to {user.email}")
                else:
                    print(f"❌ Failed to send password reset email to {user.email}")
            except Exception as email_error:
                print(f"❌ Failed to send password reset email: {str(email_error)}")
            
            return {
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, 200
        except Exception as e:
            db.session.rollback()
            print(f"Password reset error: {str(e)}")
            return {
                'message': 'If an account exists with this email, a password reset link has been sent.'
            }, 200


@auth_ns.route('/verify-reset-code')
class VerifyResetCode(Resource):
    @auth_ns.expect(verify_reset_code_model)
    def post(self):
        """Verify password reset code"""
        data = request.json
        email = data.get('email')
        code = data.get('code')
        
        if not email or not code:
            return {'message': 'Email and code are required'}, 400
        
        if not code.isdigit() or len(code) != 6:
            return {'message': 'Invalid code format. Code must be 6 digits.'}, 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {'message': 'Invalid email or code'}, 400
        
        if not user.reset_code:
            return {'message': 'No reset code found. Please request password reset first.'}, 400
        
        # Ensure reset_code_expires is timezone-aware
        expires = user.reset_code_expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
            
        if expires < datetime.now(timezone.utc):
            return {'message': 'Reset code has expired. Please request a new one.'}, 400
        
        if user.reset_code != code:
            return {'message': 'Invalid reset code'}, 400
        
        return {'message': 'Reset code verified successfully. You can now set a new password.', 'code_valid': True}, 200


@auth_ns.route('/reset-password')
class ResetPassword(Resource):
    @auth_ns.expect(reset_password_model)
    def post(self):
        """Reset password with 6-digit code"""
        data = request.json
        email = data.get('email')
        code = data.get('code')
        new_password = data.get('new_password')
        
        if not email or not code or not new_password:
            return {'message': 'Email, code, and new password are required'}, 400
        
        if not code.isdigit() or len(code) != 6:
            return {'message': 'Invalid code format. Code must be 6 digits.'}, 400
        
        # Validate password strength
        is_valid, error_message = validate_password_strength(new_password)
        if not is_valid:
            return {'message': error_message}, 400
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {'message': 'Invalid credentials'}, 400
        
        if not user.reset_code:
            return {'message': 'No reset code found. Please request password reset first.'}, 400
        
        # Ensure reset_code_expires is timezone-aware
        expires = user.reset_code_expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
            
        if expires < datetime.now(timezone.utc):
            return {'message': 'Reset code has expired. Please request a new one.'}, 400
        
        if user.reset_code != code:
            return {'message': 'Invalid reset code'}, 400
        
        # Check if new password is the same as the current password
        if user.check_password(new_password):
            return {'message': 'New password cannot be the same as your current password. Please choose a different password.'}, 400
        
        try:
            user.set_password(new_password)
            user.reset_code = None
            user.reset_code_expires = None
            db.session.commit()
            
            try:
                html_content = get_password_changed_email(user.first_name)
                send_brevo_email(
                    recipient_email=user.email,
                    subject='Password Changed - MediScan',
                    html_content=html_content
                )
            except Exception as email_error:
                print(f"Failed to send password change confirmation: {str(email_error)}")
            
            return {'message': 'Password reset successfully. You can now log in with your new password.'}, 200
        except Exception as e:
            db.session.rollback()
            return {'message': 'Password reset failed', 'error': str(e)}, 400


@auth_ns.route('/change-password')
class ChangePassword(Resource):
    @auth_ns.expect(change_password_model)
    def post(self):
        """Change user password"""
        try:
            data = request.json
            email = data.get('email')
            old_password = data.get('old_password')
            new_password = data.get('new_password')
            
            if not email or not old_password or not new_password:
                return {'message': 'Please provide email, current password, and new password'}, 400
                
            user = User.query.filter_by(email=email).first()
            
            if not user:
                return {'message': 'No account found with this email address'}, 404
                
            if not user.check_password(old_password):
                return {'message': 'The current password you entered is incorrect'}, 401
                
            if old_password == new_password:
                return {'message': 'New password cannot be the same as your current password'}, 400
                
            # Validate password strength
            is_valid, error_message = validate_password_strength(new_password)
            if not is_valid:
                return {'message': error_message}, 400
                
            try:
                user.set_password(new_password)
                db.session.commit()
                
                try:
                    html_content = get_password_changed_email(user.first_name)
                    send_brevo_email(
                        recipient_email=user.email,
                        subject='Password Changed - MediScan',
                        html_content=html_content
                    )
                except Exception as email_error:
                    print(f"Failed to send password change confirmation: {str(email_error)}")
                
                return {'message': 'Password changed successfully'}, 200
            except Exception as e:
                db.session.rollback()
                print(f"Database error during password change: {str(e)}")
                return {'message': 'An internal error occurred while changing password. Please try again.'}, 500
                
        except Exception as e:
            return {'message': 'Invalid request format', 'error': str(e)}, 400
