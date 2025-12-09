from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity

from models import db, User, Report, ReportField, AdditionalField
from config import send_brevo_email, Config
from email_templates import get_test_email

# Create namespace
user_ns = Namespace('users', description='User operations')

# API Models
user_update_model = user_ns.model('UserUpdate', {
    'first_name': fields.String(description='First name'),
    'last_name': fields.String(description='Last name'),
    'phone_number': fields.String(description='Phone number'),
    'medical_history': fields.String(description='Medical history'),
    'allergies': fields.String(description='Allergies information')
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
            'first_name': user.first_name,
            'last_name': user.last_name,
            'date_of_birth': str(user.date_of_birth),
            'phone_number': user.phone_number,
            'medical_history': user.medical_history,
            'allergies': user.allergies,
            'created_at': str(user.created_at)
        }

    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    @user_ns.expect(user_update_model)
    def put(self):
        """Update user profile"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404

        data = request.json
        try:
            if 'first_name' in data:
                user.first_name = data['first_name']
            if 'last_name' in data:
                user.last_name = data['last_name']
            if 'phone_number' in data:
                user.phone_number = data['phone_number']
            if 'medical_history' in data:
                user.medical_history = data['medical_history']
            if 'allergies' in data:
                user.allergies = data['allergies']

            db.session.commit()
            return {'message': 'Profile updated successfully'}, 200
        except Exception as e:
            db.session.rollback()
            return {'message': 'Update failed', 'error': str(e)}, 400






@user_ns.route('/delete-account')
class DeleteAccount(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def delete(self):
        """Delete current user's account and all associated data"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
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
