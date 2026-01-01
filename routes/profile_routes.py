from flask import request
from flask_restx import Resource, Namespace, fields
from flask_jwt_extended import jwt_required, get_jwt_identity
from models import db, User, Profile, Report, ReportField, AdditionalField, ReportFile
from datetime import datetime

profile_ns = Namespace('profiles', description='Managed Profile operations')

profile_model = profile_ns.model('Profile', {
    'id': fields.Integer(readOnly=True, description='Profile ID'),
    'first_name': fields.String(required=True, description='First name'),
    'last_name': fields.String(description='Last name'),
    'date_of_birth': fields.String(description='Date of Birth (YYYY-MM-DD)'),
    'gender': fields.String(description='Gender'),
    'relationship': fields.String(required=True, description='Relationship to owner (e.g., Son, Father, Self)'),
    'created_at': fields.String(readOnly=True, description='Profile creation date')
})

@profile_ns.route('/')
class ProfileList(Resource):
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.marshal_list_with(profile_model)
    def get(self):
        """List all profiles managed by or shared with the current user"""
        current_user_id = int(get_jwt_identity())
        
        # Profiles created by the current user
        owned_profiles = Profile.query.filter_by(creator_id=current_user_id).all()

        # Profiles shared with the current user
        from models import ProfileShare as ProfileShareModel
        shared_entries = ProfileShareModel.query.filter_by(shared_with_user_id=current_user_id).all()
        shared_profiles = [entry.profile for entry in shared_entries]
        
        # Combine and remove duplicates (if a profile is both owned and shared, though unlikely by design)
        all_profiles = {profile.id: profile for profile in owned_profiles + shared_profiles}.values()
        
        return list(all_profiles)

    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.expect(profile_model)
    def post(self):
        """Create a new managed profile"""
        current_user_id = int(get_jwt_identity())
        data = request.json
        
        dob = None
        if data.get('date_of_birth'):
            try:
                dob = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
            except ValueError:
                return {'message': 'Invalid date format. Use YYYY-MM-DD'}, 400

        new_profile = Profile(
            creator_id=current_user_id,
            first_name=data['first_name'],
            last_name=data.get('last_name'),
            date_of_birth=dob,
            gender=data.get('gender'),
            relationship=data.get('relationship', 'Other')
        )
        
        db.session.add(new_profile)
        db.session.commit()
        
        return {'message': 'Profile created successfully', 'id': new_profile.id}, 201

@profile_ns.route('/<int:id>')
class ProfileDetail(Resource):
    @profile_ns.doc(
        security='Bearer Auth',
        params={'X-Access-Session-Token': 'Session token from access verification (optional)'}
    )
    @jwt_required()
    @profile_ns.marshal_with(profile_model)
    def get(self, id):
        """Get a specific profile's details (requires access verification for sensitive data)"""
        from utils.access_verification import verify_session_token, check_access_permission, create_access_verification, send_verification_otp
        from models import User
        
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        # Check if the user owns the profile
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        
        # If not owned, check if it's shared with the user
        if not profile:
            from models import ProfileShare as ProfileShareModel
            shared_entry = ProfileShareModel.query.filter_by(profile_id=id, shared_with_user_id=current_user_id).first()
            if shared_entry:
                profile = shared_entry.profile

        if not profile:
            return {'message': 'Profile not found or you do not have access'}, 404
        
        # التحقق من الوصول للبيانات الحساسة
        session_token = request.headers.get('X-Access-Session-Token')
        
        if session_token:
            has_access, verification = verify_session_token(
                current_user_id,
                session_token,
                'profile',
                id
            )
            if has_access:
                return profile
        
        # لا يوجد session token صالح - التحقق من الحاجة للتحقق
        has_access, needs_verification, _ = check_access_permission(
            current_user_id,
            'profile',
            id,
            require_verification=True
        )
        
        if needs_verification:
            # Create verification request (only sends email if new)
            verification, is_new = create_access_verification(
                current_user_id,
                'profile',
                id,
                method='otp'
            )
            # Only send email if it's a new verification request
            if is_new:
                send_verification_otp(user, verification)
            
            return {
                'message': 'Access verification required for sensitive data',
                'requires_verification': True,
                'verification_id': verification.id,
                'instructions': 'Use /auth/verify-access-code with the verification code sent to your email'
            }, 403
        
        return profile

    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.expect(profile_model)
    def put(self, id):
        """Update a managed profile"""
        current_user_id = int(get_jwt_identity())
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found or you are not the owner'}, 404
            
        data = request.json
        if 'first_name' in data: profile.first_name = data['first_name']
        if 'last_name' in data: profile.last_name = data['last_name']
        if 'gender' in data: profile.gender = data['gender']
        if 'relationship' in data: profile.relationship = data['relationship']
        
        if data.get('date_of_birth'):
            try:
                profile.date_of_birth = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
            except ValueError:
                return {'message': 'Invalid date format. Use YYYY-MM-DD'}, 400

        db.session.commit()
        return {'message': 'Profile updated successfully'}

    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    def delete(self, id):
        """Delete a managed profile (and unlink its reports)"""
        current_user_id = int(get_jwt_identity())
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        
        if not profile:
            return {'message': 'Profile not found'}, 404
            
        if profile.relationship == 'Self':
            return {'message': 'Cannot delete your own primary profile'}, 400

        # Unlink reports before deleting
        Report.query.filter_by(profile_id=profile.id).update({Report.profile_id: None})
        
        db.session.delete(profile)
        db.session.commit()
        return {'message': 'Profile deleted successfully'}


@profile_ns.route('/<int:id>/share')
class ProfileShare(Resource):
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.expect(profile_ns.model('ProfileShareRequest', {
        'email': fields.String(required=True, description="Email of user to share with"),
        'access_level': fields.String(default='view', description="view, upload, or manage")
    }))
    def post(self, id):
        """Grant access to a profile to another user"""
        current_user_id = int(get_jwt_identity())
        data = request.json
        
        # 1. Verify ownership (only creator can share for now)
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found or you are not the owner'}, 404
            
        # 2. Find target user
        target_user = User.query.filter_by(email=data['email']).first()
        if not target_user:
            return {'message': 'User with this email not found'}, 404
            
        if target_user.id == current_user_id:
            return {'message': 'Cannot share with yourself'}, 400

        # 3. Create or Update Share
        from models import ProfileShare as ProfileShareModel
        
        existing_share = ProfileShareModel.query.filter_by(
            profile_id=id, 
            shared_with_user_id=target_user.id
        ).first()
        
        if existing_share:
            existing_share.access_level = data.get('access_level', 'view')
            msg = "Access updated"
        else:
            new_share = ProfileShareModel(
                profile_id=id,
                shared_with_user_id=target_user.id,
                access_level=data.get('access_level', 'view')
            )
            db.session.add(new_share)
            msg = "Access granted"
            
        db.session.commit()

        # Send Notification
        try:
            from utils.notification_service import notify_profile_share
            sharer = User.query.get(current_user_id)
            sharer_name = f"{sharer.first_name} {sharer.last_name or ''}".strip()
            profile_name = f"{profile.first_name} {profile.last_name or ''}".strip()
            notify_profile_share(sharer_name, profile_name, target_user.id, profile.id)
        except Exception as e:
            print(f"Notification failed: {e}")

        return {'message': msg}


@profile_ns.route('/<int:id>/transfer')
class ProfileTransfer(Resource):
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.expect(profile_ns.model('ProfileTransferRequest', {
        'email': fields.String(required=True, description="Email of the user to transfer ownership to")
    }))
    def post(self, id):
        """Transfer ownership of a profile to another user (e.g. child turns 18)"""
        current_user_id = int(get_jwt_identity())
        data = request.json
        
        # 1. Verify Ownership
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found or you are not the owner'}, 404
            
        if profile.relationship == 'Self':
            return {'message': 'Cannot transfer your own primary profile'}, 400

        # 2. Verify Target User
        target_user = User.query.filter_by(email=data['email']).first()
        if not target_user:
            return {'message': 'Target user not found'}, 404
            
        if target_user.id == current_user_id:
            return {'message': 'Cannot transfer to yourself'}, 400
            
        # 3. Execute Transfer
        # - Update creator to new user
        # - Set relationship to 'Self' (it becomes their main profile)
        old_owner_id = profile.creator_id
        profile.creator_id = target_user.id
        profile.relationship = 'Self'
        
        # 4. Auto-Share back to Old Owner (so they don't lose access)
        from models import ProfileShare as ProfileShareModel
        
        # Check if share already exists (unlikely given ownership, but safety first)
        existing_share = ProfileShareModel.query.filter_by(
            profile_id=id,
            shared_with_user_id=old_owner_id
        ).first()
        
        if not existing_share:
            new_share = ProfileShareModel(
                profile_id=id,
                shared_with_user_id=old_owner_id,
                access_level='manage' # Give parent full manage access by default
            )
            db.session.add(new_share)
        else:
            existing_share.access_level = 'manage'
            
        db.session.commit()
        
        return {'message': f'Profile ownership transferred to {target_user.email}. You retain manage access.'}

@profile_ns.route('/shared_with_me')
class SharedProfiles(Resource):
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.marshal_list_with(profile_model)
    def get(self):
        """List profiles shared with me by others"""
        current_user_id = int(get_jwt_identity())
        from models import ProfileShare as ProfileShareModel
        
        # Join ProfileShare with Profile to fetch the actual profile data
        shared_entries = ProfileShareModel.query.filter_by(shared_with_user_id=current_user_id).all()
        profiles = [entry.profile for entry in shared_entries]
        
        return profiles

@profile_ns.route('/<int:id>/reports')
class ProfileReports(Resource):
    @profile_ns.doc(
        security='Bearer Auth',
        params={'X-Access-Session-Token': 'Session token from access verification (required for sensitive data)'}
    )
    @jwt_required()
    def get(self, id):
        """Get all reports for a specific profile (owned or shared) - requires access verification"""
        from utils.access_verification import verify_session_token, check_access_permission, create_access_verification, send_verification_otp
        from models import User, ProfileShare
        
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        # 1. Check Ownership
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        
        # 2. Check Shared Access if not owner
        if not profile:
            share = ProfileShare.query.filter_by(profile_id=id, shared_with_user_id=current_user_id).first()
            if share:
                profile = Profile.query.get(id)
            else:
                return {'message': 'Profile not found or unauthorized access'}, 404
        
        # التحقق من الوصول للبيانات الحساسة (التقارير الطبية)
        session_token = request.headers.get('X-Access-Session-Token')
        
        if session_token:
            has_access, verification = verify_session_token(
                current_user_id,
                session_token,
                'profile',
                id
            )
            if not has_access:
                return {
                    'message': 'Session token غير صالح أو منتهي الصلاحية',
                    'requires_verification': True
                }, 403
        else:
            # لا يوجد session token - التحقق من الحاجة للتحقق
            has_access, needs_verification, _ = check_access_permission(
                current_user_id,
                'profile',
                id,
                require_verification=True
            )
            
            if needs_verification:
                verification, is_new = create_access_verification(
                    current_user_id,
                    'profile',
                    id,
                    method='otp'
                )
                # Only send email if it's a new verification request
                if is_new:
                    send_verification_otp(user, verification)
                
                return {
                    'message': 'Access verification required for sensitive medical data',
                    'requires_verification': True,
                        'verification_id': verification.id,
                        'instructions': 'Use /auth/verify-access-code with the verification code sent to your email'
                    }, 403
        
        # Get all reports linked to this profile
        reports = Report.query.filter_by(
            profile_id=id
        ).order_by(Report.created_at.desc()).all()
        
        if not reports:
            return {
                'message': 'No reports found for this profile',
                'profile': {
                    'id': profile.id,
                    'first_name': profile.first_name,
                    'last_name': profile.last_name,
                    'relationship': profile.relationship
                },
                'total_reports': 0,
                'reports': []
            }, 200
        
        reports_data = []
        for report in reports:
            report_fields = ReportField.query.filter_by(report_id=report.id).order_by(ReportField.id).all()
            fields_data = []
            for field in report_fields:
                fields_data.append({
                    'id': field.id,
                    'field_name': field.field_name,
                    'field_value': field.field_value,
                    'field_unit': field.field_unit,
                    'normal_range': field.normal_range,
                    'is_normal': field.is_normal,
                    'field_type': field.field_type,
                    'category': field.category,
                    'notes': field.notes,
                    'created_at': str(field.created_at)
                })
            
            additional_fields = AdditionalField.query.filter_by(report_id=report.id).all()
            additional_fields_data = []
            for add_field in additional_fields:
                additional_fields_data.append({
                    'id': add_field.id,
                    'field_name': add_field.field_name,
                    'field_value': add_field.field_value,
                    'category': add_field.category,
                    'merged_at': str(add_field.approved_at) if add_field.approved_at else None
                })
            
            report_files = ReportFile.query.filter_by(report_id=report.id).order_by(ReportFile.id).all()
            images_info = [
                {'index': idx, 'filename': f.original_filename, 'file_type': f.file_type, 'url': f'/reports/{report.id}/images/{idx}'}
                for idx, f in enumerate(report_files, 1)
            ]
            
            reports_data.append({
                'report_id': report.id,
                'report_date': str(report.report_date),
                'report_name': report.report_name,
                'report_type': report.report_type,
                'doctor_names': report.doctor_names,
                'patient_age': report.patient_age,
                'patient_gender': report.patient_gender,
                'created_at': str(report.created_at),
                'total_fields': len(fields_data),
                'total_images': len(images_info),
                'images': images_info,
                'fields': fields_data,
                'additional_fields': additional_fields_data
            })

        return {
            'message': 'Reports retrieved successfully',
            'profile': {
                'id': profile.id,
                'first_name': profile.first_name,
                'last_name': profile.last_name,
                'relationship': profile.relationship
            },
            'total_reports': len(reports),
            'reports': reports_data
        }, 200
# force sync check
