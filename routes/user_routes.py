from flask import request
import re
from datetime import datetime, timezone
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, User, Report, ReportField, AdditionalField, ReportFile, UserDevice, Notification
from config import send_brevo_email, Config
from email_templates import get_test_email
import os


# Create namespace
user_ns = Namespace('users', description='User operations')

# API Models
user_update_model = user_ns.model('UserUpdate', {
    'first_name': fields.String(description='First name'),
    'last_name': fields.String(description='Last name'),
    'phone_number': fields.String(description='Phone number'),
    'date_of_birth': fields.String(description='Date of Birth (YYYY-MM-DD)')
})

delete_user_model = user_ns.model('DeleteUser', {
    'user_id': fields.Integer(required=True, description='ID of the user to delete'),
    'admin_password': fields.String(required=True, description='Admin password for testing')
})

test_email_model = user_ns.model('TestEmail', {
    'to_email': fields.String(required=True, description='Recipient email address'),
    'subject': fields.String(required=True, description='Email subject'),
    'body': fields.String(required=True, description='Email body/message'),
    'admin_password': fields.String(required=True, description='Admin password (testingAdmin)')
})

token_model = user_ns.model('RegisterToken', {
    'fcm_token': fields.String(required=True, description='Firebase Cloud Messaging Token'),
    'device_type': fields.String(description='Device type (android, ios, web)')
})


@user_ns.route('/register-token')
class RegisterToken(Resource):
    @user_ns.doc(security='Bearer Auth')
    @user_ns.expect(token_model)
    @jwt_required()
    def post(self):
        """Register FCM token for push notifications"""
        current_user_id = int(get_jwt_identity())
        data = request.get_json()
        
        fcm_token = data.get('fcm_token')
        device_type = data.get('device_type', 'unknown')
        
        if not fcm_token:
            return {'message': 'Token is required'}, 400
            
        # Check if token already exists
        existing_device = UserDevice.query.filter_by(fcm_token=fcm_token).first()
        
        if existing_device:
            # Update user_id if changed (e.g. logout/login with different user)
            existing_device.user_id = current_user_id
            existing_device.last_active = datetime.now(timezone.utc)
            existing_device.device_type = device_type
        else:
            # Create new device
            new_device = UserDevice(
                user_id=current_user_id,
                fcm_token=fcm_token,
                device_type=device_type
            )
            db.session.add(new_device)
            
        db.session.commit()
        
        return {'message': 'Token registered successfully'}, 200




@user_ns.route('/profile')
class UserProfile(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get user profile information"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404

        return {
            'email': user.email,
            'biometric_allowed': getattr(user, 'biometric_allowed', True),
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_of_birth': user.date_of_birth.strftime('%Y-%m-%d') if user.date_of_birth else None,
            'phone_number': user.phone_number,
            'gender': user.gender,
            'profile_image': user.profile_image,
            'profile_image_url': f'/users/profile-image/{user.id}',
            'created_at': str(user.created_at)
        }

    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def put(self):
        """Update user profile (supports multipart/form-data for image upload)"""
        from werkzeug.utils import secure_filename
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404

        try:
            # Handle form data (for file upload)
            first_name = request.form.get('first_name')
            last_name = request.form.get('last_name')
            phone_number = request.form.get('phone_number')
            date_of_birth = request.form.get('date_of_birth')
            profile_image = request.files.get('profile_image')
            
            # 1. Name Validation
            name_pattern = re.compile(r"^[a-zA-Z\s]+$")
            
            if first_name:
                if not name_pattern.match(first_name):
                    return {'message': 'First name must contain only letters and spaces'}, 400
                user.first_name = first_name
                
            if last_name:
                if not name_pattern.match(last_name):
                    return {'message': 'Last name must contain only letters and spaces'}, 400
                user.last_name = last_name

            # 2. Date of Birth Handling
            if date_of_birth:
                try:
                    dob_obj = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
                    user.date_of_birth = dob_obj
                except ValueError:
                    return {'message': 'Invalid date format. Use YYYY-MM-DD'}, 400

            # 3. Phone Number
            if phone_number:
                user.phone_number = phone_number
            
            # 4. Profile Image Upload
            if profile_image and profile_image.filename:
                # Validate file type
                allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
                file_ext = profile_image.filename.rsplit('.', 1)[1].lower() if '.' in profile_image.filename else ''
                
                if file_ext not in allowed_extensions:
                    return {'message': 'Invalid image format. Allowed: png, jpg, jpeg, gif, webp'}, 400
                
                # Create user profile folder
                profile_folder = os.path.join(Config.UPLOAD_FOLDER, f'user_{current_user_id}', 'profile_img')
                os.makedirs(profile_folder, exist_ok=True)
                
                # Delete old profile image if not default
                if user.profile_image and user.profile_image != 'default.jpg':
                    old_image_path = os.path.join(profile_folder, user.profile_image)
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                        print(f"🗑️ Deleted old profile image: {old_image_path}")
                
                # Save new image with fixed name (profile.ext)
                new_filename = f'profile.{file_ext}'
                image_path = os.path.join(profile_folder, new_filename)
                profile_image.save(image_path)
                
                user.profile_image = new_filename
                print(f"✅ Saved new profile image: {image_path}")

            db.session.commit()
            return {
                'message': 'Profile updated successfully',
                'profile_image_url': f'/users/profile-image/{user.id}'
            }, 200
        except Exception as e:
            db.session.rollback()
            print(f"❌ Profile update error: {str(e)}")
            return {'message': 'Update failed', 'error': str(e)}, 400






@user_ns.route('/delete-account')
class DeleteAccount(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def delete(self):
        """Delete current user's account and all associated data - requires password confirmation"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Get password from request body
        data = request.json
        password = data.get('password') if data else None
        
        if not password:
            return {'message': 'Password is required to delete account'}, 400
        
        # Verify password
        if not user.check_password(password):
            return {'message': 'Incorrect password'}, 401
        
        try:
            # Manually clean up related records to ensure thorough deletion
            # (Even with cascades, explicit cleanup handles potential ORM caching issues)
            reports = Report.query.filter_by(user_id=current_user_id).all()
            for report in reports:
                # Delete files associated with report
                # Note: This logic assumes physical file deletion is handled elsewhere or is acceptable to keep orphaned files
                # ideally we would iterate and delete physical files here too using report.get_file_path() or ReportFile records
                
                ReportField.query.filter_by(report_id=report.id).delete()
                AdditionalField.query.filter_by(report_id=report.id).delete()
                ReportFile.query.filter_by(report_id=report.id).delete()
                db.session.delete(report)
            
            # Delete any AdditionalFields not linked to reports (if any)
            AdditionalField.query.filter_by(user_id=current_user_id).delete()
            
            db.session.delete(user)
            db.session.commit()
            
            return {
                'message': 'Account deleted successfully',
                'deleted_user_id': current_user_id,
                'email': user.email
            }, 200
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Failed to delete account: {str(e)}")
            return {
                'message': 'Failed to delete account',
                'error': str(e)
            }, 500



@user_ns.route('/delete-user-testing')
class DeleteUserTesting(Resource):
    @user_ns.expect(delete_user_model)
    def delete(self):
        """Delete a user by ID - FOR TESTING ONLY"""
        data = request.json
        user_id = data.get('user_id')
        admin_password = data.get('admin_password')
        
        if not user_id or not admin_password:
            return {'message': 'user_id and admin_password are required'}, 400
        
        if admin_password != 'testingAdmin':
            return {'message': 'Invalid admin password'}, 403
        
        user = User.query.get(user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        try:
            reports = Report.query.filter_by(user_id=user_id).all()
            for report in reports:
                ReportField.query.filter_by(report_id=report.id).delete()
                AdditionalField.query.filter_by(report_id=report.id).delete()
                db.session.delete(report)
            
            db.session.delete(user)
            db.session.commit()
            
            return {
                'message': f'User {user.email} (ID: {user_id}) deleted successfully (TESTING MODE)',
                'deleted_user_id': user_id,
                'deleted_email': user.email
            }, 200
        except Exception as e:
            db.session.rollback()
            return {
                'message': 'Failed to delete user',
                'error': str(e)
            }, 500




@user_ns.route('/profile-image/<int:user_id>')
class ProfileImage(Resource):
    def get(self, user_id):
        """Get user's profile image"""
        from flask import send_file
        
        user = User.query.get(user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Check for custom profile image
        if user.profile_image and user.profile_image != 'default.jpg':
            profile_folder = os.path.join(Config.UPLOAD_FOLDER, f'user_{user_id}', 'profile_img')
            image_path = os.path.join(profile_folder, user.profile_image)
            
            if os.path.exists(image_path):
                return send_file(image_path, mimetype='image/jpeg')
        
        # Fallback to default image
        default_path = os.path.join('static', 'default.jpg')
        if os.path.exists(default_path):
            return send_file(default_path, mimetype='image/jpeg')
        
        return {'message': 'Profile image not found'}, 404


@user_ns.route('/test-email')
class TestEmail(Resource):
    @user_ns.expect(test_email_model)
    def post(self):
        """Test email sending - FOR TESTING ONLY"""
        data = request.json
        to_email = data.get('to_email')
        subject = data.get('subject')
        body = data.get('body')
        admin_password = data.get('admin_password')
        
        if not all([to_email, subject, body, admin_password]):
            return {'message': 'All fields are required: to_email, subject, body, admin_password'}, 400
        
        if admin_password != 'testingAdmin':
            return {'message': 'Invalid admin password'}, 403
        
        try:
            print(f"\n{'='*80}")
            print(f"📧 TEST EMAIL SEND")
            print(f"From: {Config.SENDER_EMAIL}")
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(f"Using Brevo API")
            print(f"{'='*80}\n")
            
            html_content = get_test_email(body)
            
            success = send_brevo_email(
                recipient_email=to_email,
                subject=subject,
                html_content=html_content
            )
            
            if success:
                print(f"✅ Test email sent successfully to {to_email}\n")
                return {
                    'message': 'Email sent successfully using Brevo API!',
                    'details': {
                        'from': Config.SENDER_EMAIL,
                        'to': to_email,
                        'subject': subject,
                        'method': 'Brevo Transactional Email API'
                    }
                }, 200
            else:
                return {
                    'message': 'Failed to send email via Brevo API',
                    'details': {
                        'from': Config.SENDER_EMAIL,
                        'to': to_email
                    }
                }, 500
            
        except Exception as e:
            print(f"❌ Failed to send test email: {str(e)}")
            import traceback
            traceback.print_exc()
            
            return {
                'message': 'Failed to send email',
                'error': str(e)
            }, 500


notification_model = user_ns.model('Notification', {
    'id': fields.Integer(description='Notification ID'),
    'title': fields.String(description='Notification Title'),
    'message': fields.String(description='Notification Message'),
    'type': fields.String(attribute='notification_type', description='Notification Type'),
    'is_read': fields.Boolean(description='Is Read Status'),
    'created_at': fields.String(description='Creation Date'),
    'data': fields.Raw(description='Additional Data')
})

@user_ns.route('/notifications')
class NotificationList(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    @user_ns.marshal_list_with(notification_model)
    def get(self):
        """Fetch a list of all historical notifications for the authenticated user"""
        current_user_id = int(get_jwt_identity())
        notifications = Notification.query.filter_by(user_id=current_user_id).order_by(Notification.created_at.desc()).all()
        return notifications

@user_ns.route('/notifications/<int:id>/read')
class NotificationRead(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def post(self, id):
        """Mark a specific notification as read"""
        current_user_id = int(get_jwt_identity())
        notification = Notification.query.filter_by(id=id, user_id=current_user_id).first()
        
        if not notification:
            return {'message': 'Notification not found'}, 404
            
        notification.is_read = True
        db.session.commit()
        
        return {'message': 'Notification marked as read'}, 200
