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
    get_password_reset_email_with_link,
    get_password_changed_email
)
from utils.password_validator import validate_password_strength

# Create namespace
auth_ns = Namespace('auth', description='Authentication operations')

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
            # Generate both a 6-digit code and a secure token
            reset_code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
            reset_token = secrets.token_urlsafe(32)
            
            # Store both in the database (token in reset_code field, code for fallback)
            user.reset_code = reset_token  # Store token for one-click verification
            user.reset_code_expires = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.session.commit()
            
            print(f"\n{'='*80}")
            print(f"🔑 PASSWORD RESET for {user.email}")
            print(f"   Token: {reset_token}")
            print(f"   Code (fallback): {reset_code}")
            print(f"   Expires at: {user.reset_code_expires}")
            print(f"   Verification URL: http://localhost:8051/auth/verify-password-reset/{reset_token}")
            print(f"{'='*80}\n")
            
            try:
                # Use new email template with verification button
                html_content = get_password_reset_email_with_link(
                    user.first_name, 
                    reset_token, 
                    reset_code,
                    base_url="http://localhost:8051"
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


@auth_ns.route('/verify-password-reset/<string:token>')
class VerifyPasswordResetToken(Resource):
    def get(self, token):
        """Verify password reset token from email link (one-click verification)"""
        # Find user with this reset token
        user = User.query.filter_by(reset_code=token).first()
        
        if not user:
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Invalid Reset Link - MediScan</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }
                    .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; text-align: center; }
                    h1 { color: #ef4444; margin: 0 0 16px 0; font-size: 24px; }
                    p { color: #6b7280; margin: 0 0 24px 0; line-height: 1.6; }
                    a { display: inline-block; background-color: #60a5fa; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; }
                    a:hover { background-color: #3b82f6; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>❌ Invalid Reset Link</h1>
                    <p>This password reset link is invalid or has already been used.</p>
                    <a href="http://localhost:8051/auth/forgot-password">Request New Reset Link</a>
                </div>
            </body>
            </html>
            """, 400
        
        # Check if token is expired
        expires = user.reset_code_expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
            
        if expires < datetime.now(timezone.utc):
            return """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Link Expired - MediScan</title>
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }
                    .container { background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; text-align: center; }
                    h1 { color: #f59e0b; margin: 0 0 16px 0; font-size: 24px; }
                    p { color: #6b7280; margin: 0 0 24px 0; line-height: 1.6; }
                    a { display: inline-block; background-color: #60a5fa; color: white; text-decoration: none; padding: 12px 24px; border-radius: 8px; font-weight: 600; }
                    a:hover { background-color: #3b82f6; }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>⏰ Link Expired</h1>
                    <p>This password reset link has expired. Reset links are valid for 15 minutes.</p>
                    <a href="http://localhost:8051/auth/forgot-password">Request New Reset Link</a>
                </div>
            </body>
            </html>
            """, 400
        
        # Token is valid - show password reset form
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Reset Your Password - MediScan</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #f9fafb; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 20px; }}
                .container {{ background: white; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; width: 100%; }}
                h1 {{ color: #111827; margin: 0 0 8px 0; font-size: 24px; text-align: center; }}
                .subtitle {{ color: #6b7280; margin: 0 0 32px 0; text-align: center; font-size: 14px; }}
                .form-group {{ margin-bottom: 20px; }}
                label {{ display: block; color: #374151; font-weight: 600; margin-bottom: 8px; font-size: 14px; }}
                input {{ width: 100%; padding: 12px; border: 2px solid #e5e7eb; border-radius: 8px; font-size: 16px; box-sizing: border-box; }}
                input:focus {{ outline: none; border-color: #60a5fa; }}
                button {{ width: 100%; background-color: #60a5fa; color: white; border: none; padding: 14px; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; }}
                button:hover {{ background-color: #3b82f6; }}
                button:disabled {{ background-color: #9ca3af; cursor: not-allowed; }}
                .message {{ padding: 12px; border-radius: 8px; margin-bottom: 20px; display: none; }}
                .message.error {{ background-color: #fee2e2; color: #991b1b; border: 1px solid #fecaca; }}
                .message.success {{ background-color: #d1fae5; color: #065f46; border: 1px solid #a7f3d0; }}
                .requirements {{ background-color: #eff6ff; padding: 16px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; }}
                .requirements ul {{ margin: 8px 0 0 0; padding-left: 20px; color: #4b5563; }}
                .requirements li {{ margin: 4px 0; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>🔐 Reset Your Password</h1>
                <p class="subtitle">Hello {user.first_name}, enter your new password below</p>
                
                <div id="message" class="message"></div>
                
                <div class="requirements">
                    <strong style="color: #1f2937;">Password Requirements:</strong>
                    <ul>
                        <li>At least 8 characters long</li>
                        <li>Contains uppercase and lowercase letters</li>
                        <li>Contains at least one number</li>
                        <li>Contains at least one special character</li>
                    </ul>
                </div>
                
                <form id="resetForm">
                    <div class="form-group">
                        <label for="password">New Password</label>
                        <input type="password" id="password" name="password" required minlength="8">
                    </div>
                    <div class="form-group">
                        <label for="confirmPassword">Confirm New Password</label>
                        <input type="password" id="confirmPassword" name="confirmPassword" required minlength="8">
                    </div>
                    <button type="submit" id="submitBtn">Reset Password</button>
                </form>
            </div>
            
            <script>
                const form = document.getElementById('resetForm');
                const messageDiv = document.getElementById('message');
                const submitBtn = document.getElementById('submitBtn');
                
                function showMessage(text, type) {{
                    messageDiv.textContent = text;
                    messageDiv.className = 'message ' + type;
                    messageDiv.style.display = 'block';
                }}
                
                form.addEventListener('submit', async (e) => {{
                    e.preventDefault();
                    
                    const password = document.getElementById('password').value;
                    const confirmPassword = document.getElementById('confirmPassword').value;
                    
                    if (password !== confirmPassword) {{
                        showMessage('Passwords do not match!', 'error');
                        return;
                    }}
                    
                    submitBtn.disabled = true;
                    submitBtn.textContent = 'Resetting...';
                    
                    try {{
                        const response = await fetch('/auth/reset-password', {{
                            method: 'POST',
                            headers: {{
                                'Content-Type': 'application/json',
                            }},
                            body: JSON.stringify({{
                                email: '{user.email}',
                                code: '{token}',
                                new_password: password
                            }})
                        }});
                        
                        const data = await response.json();
                        
                        if (response.ok) {{
                            showMessage('✅ ' + data.message, 'success');
                            setTimeout(() => {{
                                window.location.href = 'http://localhost:8051/swagger';
                            }}, 2000);
                        }} else {{
                            showMessage('❌ ' + data.message, 'error');
                            submitBtn.disabled = false;
                            submitBtn.textContent = 'Reset Password';
                        }}
                    }} catch (error) {{
                        showMessage('❌ Network error. Please try again.', 'error');
                        submitBtn.disabled = false;
                        submitBtn.textContent = 'Reset Password';
                    }}
                }});
            </script>
        </body>
        </html>
        """, 200


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
