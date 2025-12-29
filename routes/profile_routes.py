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
        """List all profiles managed by the current user"""
        current_user_id = int(get_jwt_identity())
        return Profile.query.filter_by(creator_id=current_user_id).all()

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
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.marshal_with(profile_model)
    def get(self, id):
        """Get a specific profile's details"""
        current_user_id = int(get_jwt_identity())
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found'}, 404
        return profile

    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    @profile_ns.expect(profile_model)
    def put(self, id):
        """Update a managed profile"""
        current_user_id = int(get_jwt_identity())
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found'}, 404
            
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


@profile_ns.route('/<int:id>/reports')
class ProfileReports(Resource):
    @profile_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, id):
        """Get all reports for a specific profile"""
        current_user_id = int(get_jwt_identity())
        
        # Verify user owns this profile
        profile = Profile.query.filter_by(id=id, creator_id=current_user_id).first()
        if not profile:
            return {'message': 'Profile not found or unauthorized access'}, 404
        
        # Get all reports for this profile
        reports = Report.query.filter_by(
            user_id=current_user_id,
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
            
            # Get images info for this report from database
            report_files = ReportFile.query.filter_by(report_id=report.id).order_by(ReportFile.id).all()
            images_info = []
            
            for idx, report_file in enumerate(report_files, 1):
                images_info.append({
                    'index': idx,
                    'filename': report_file.original_filename,
                    'file_type': report_file.file_type,
                    'url': f'/reports/{report.id}/images/{idx}'
                })
            
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
