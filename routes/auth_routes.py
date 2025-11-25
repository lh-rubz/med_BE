from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import create_access_token
from datetime import datetime, timedelta, timezone
import secrets

from models import db, User
from config import send_brevo_email
from email_templates import (
    get_verification_email,
    get_resend_verification_email,
    get_password_reset_email,
    get_password_changed_email
)

# Create namespace
auth_ns = Namespace('auth', description='Authentication operations')

# API Models
register_model = auth_ns.model('Registration', {
    'email': fields.String(required=True, description='User email address'),
    'password': fields.String(required=True, description='User password'),
    'first_name': fields.String(required=True, description='First name'),
    'last_name': fields.String(required=True, description='Last name'),
    'date_of_birth': fields.Date(required=True, description='Date of birth (YYYY-MM-DD)'),
    'phone_number': fields.String(required=True, description='Phone number'),
    'medical_history': fields.String(required=False, description='Medical history'),
    'allergies': fields.String(required=False, description='Allergies information')
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


@auth_ns.route('/register')
class Register(Resource):
    @auth_ns.expect(register_model)
    def post(self):
        """Register a new user"""
        data = request.json

        if User.query.filter_by(email=data['email']).first():
            return {'message': 'Email already registered'}, 409

        try:
            verification_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            
            new_user = User(
                email=data['email'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                date_of_birth=datetime.strptime(str(data['date_of_birth']), '%Y-%m-%d').date(),
                phone_number=data['phone_number'],
                medical_history=data.get('medical_history', ''),
                allergies=data.get('allergies', ''),
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
        return {'access_token': access_token, 'email_verified': True}, 200


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
        
        if user.verification_code_expires < datetime.now(timezone.utc):
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
            reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            user.reset_code = reset_code
            user.reset_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.session.commit()
            
            print(f"\n{'='*80}")
            print(f"🔑 PASSWORD RESET CODE for {user.email}: {reset_code}")
            print(f"Code expires at: {user.reset_code_expires}")
            print(f"{'='*80}\n")
            
            try:
                html_content = get_password_reset_email(user.first_name, reset_code)
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
        
        user = User.query.filter_by(email=email).first()
        
        if not user:
            return {'message': 'Invalid credentials'}, 400
        
        if not user.reset_code:
            return {'message': 'No reset code found. Please request password reset first.'}, 400
        
        if user.reset_code_expires < datetime.now(timezone.utc):
            return {'message': 'Reset code has expired. Please request a new one.'}, 400
        
        if user.reset_code != code:
            return {'message': 'Invalid reset code'}, 400
        
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
