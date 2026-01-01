from flask import request, send_file, jsonify
from flask_restx import Resource, Namespace
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import glob
from collections import defaultdict
from datetime import datetime

from models import db, User, Report, ReportField, AdditionalField, ReportFile, Profile
from config import Config
from utils.medical_mappings import get_search_terms
from sqlalchemy import or_

# Create namespace
reports_ns = Namespace('reports', description='Medical reports management')


@reports_ns.route('')
class UserReports(Resource):
    @reports_ns.doc(
        security='Bearer Auth',
        params={
            'profile_id': 'Optional: Filter reports by specific profile ID',
            'X-Access-Session-Token': 'Session token from access verification (required for sensitive data)'
        }
    )
    @jwt_required()
    def get(self):
        """Get all extracted reports for the current user (optionally filtered by profile) - requires access verification for sensitive data"""
        from utils.access_verification import verify_session_token, check_access_permission, create_access_verification, send_verification_otp
        from models import ProfileShare
        
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Check for profile_id filter
        profile_id = request.args.get('profile_id')
        
        # إذا كان هناك profile_id، يلزم التحقق من الوصول
        if profile_id:
            profile_id = int(profile_id)
            
            # Verify user owns this profile or has shared access
            profile = Profile.query.filter_by(id=profile_id, creator_id=current_user_id).first()
            
            if not profile:
                share = ProfileShare.query.filter_by(profile_id=profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    profile = Profile.query.get(profile_id)
            
            if not profile:
                return {'message': 'Invalid profile_id or unauthorized access'}, 403
            
            # التحقق من الوصول للبيانات الحساسة
            session_token = request.headers.get('X-Access-Session-Token')
            
            if session_token:
                has_access, verification = verify_session_token(
                    current_user_id,
                    session_token,
                    'profile',
                    profile_id
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
                    profile_id,
                    require_verification=True
                )
                
                if needs_verification:
                    verification = create_access_verification(
                        current_user_id,
                        'profile',
                        profile_id,
                        method='otp'
                    )
                    send_verification_otp(user, verification)
                    
                    return {
                        'message': 'يتطلب التحقق من الوصول للبيانات الطبية الحساسة',
                        'requires_verification': True,
                        'verification_id': verification.id,
                        'instructions': 'استخدم /auth/verify-access-code مع كود التحقق المرسل إلى بريدك'
                    }, 403
        
        # Build query
        query = Report.query.filter_by(user_id=current_user_id)
        
        if profile_id:
            query = query.filter_by(profile_id=profile_id)
        
        reports = query.order_by(Report.created_at.desc()).all()
        
        if not reports:
            return {
                'message': 'No reports found',
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
            
            # Get profile information
            profile_info = None
            if report.profile_id:
                profile = Profile.query.get(report.profile_id)
                if profile:
                    profile_info = {
                        'id': profile.id,
                        'first_name': profile.first_name,
                        'last_name': profile.last_name,
                        'relationship': profile.relationship
                    }
            
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
                'profile_id': report.profile_id,
                'profile': profile_info,
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
            'total_reports': len(reports),
            'user': {
                'id': user.id,
                'first_name': user.first_name,
                'last_name': user.last_name
            },
            'reports': reports_data
        }, 200


@reports_ns.route('/timeline')
class Timeline(Resource):
    @reports_ns.doc(
        security='Bearer Auth',
        params={'profile_id': 'Optional: Filter timeline by specific profile ID'}
    )
    @jwt_required()
    def get(self):
        """Get chronological timeline of reports with health summaries (optionally filtered by profile)"""
        current_user_id = int(get_jwt_identity())
        
        # Check for profile_id filter
        profile_id = request.args.get('profile_id')
        
        # Build query
        query = Report.query.filter_by(user_id=current_user_id)
        
        if profile_id:
            # Verify user owns this profile or has shared access
            profile = Profile.query.filter_by(id=profile_id, creator_id=current_user_id).first()
            
            if not profile:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    profile = Profile.query.get(profile_id)
            
            if not profile:
                return {'message': 'Invalid profile_id or unauthorized access'}, 403
            query = query.filter_by(profile_id=profile_id)
            
        # Get reports ordered by date
        reports = query.order_by(Report.report_date.desc()).all()
        
        timeline_data = []
        for report in reports:
            # Count abnormal fields
            abnormal_fields = ReportField.query.filter_by(
                report_id=report.id, 
                is_normal=False
            ).all()
            
            total_fields_count = ReportField.query.filter_by(report_id=report.id).count()
            
            timeline_data.append({
                'report_id': report.id,
                'date': report.report_date.strftime('%Y-%m-%d'),
                'report_type': report.report_type or 'General Report',
                'doctor_names': report.doctor_names,
                'summary': {
                    'total_tests': total_fields_count,
                    'abnormal_count': len(abnormal_fields),
                    'abnormal_fields': [f.field_name for f in abnormal_fields]
                }
            })
            
        return {'timeline': timeline_data}, 200


@reports_ns.route('/trends')
class HealthTrends(Resource):
    @reports_ns.doc(
        security='Bearer Auth', 
        params={
            'field_name': 'Comma separated test names (e.g. Hemoglobin,WBC)',
            'profile_id': 'Optional: Filter trends by specific profile ID'
        }
    )
    @jwt_required()
    def get(self):
        """Get historical values for specific health metrics (optionally filtered by profile)"""
        current_user_id = int(get_jwt_identity())
        field_names = request.args.get('field_name', '').split(',')
        profile_id = request.args.get('profile_id')
        
        if profile_id:
            # Verify user owns this profile or has shared access
            profile = Profile.query.filter_by(id=profile_id, creator_id=current_user_id).first()
            
            if not profile:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    profile = Profile.query.get(profile_id)

            if not profile:
                return {'message': 'Invalid profile_id or unauthorized access'}, 403
        
        if not field_names or field_names == ['']:
            return {'message': 'Please provide field_name parameter'}, 400
            
        trends = {}
        for name in field_names:
            name = name.strip()
            if not name: 
                continue
                
            # Expand search terms using aliases
            search_terms = get_search_terms(name)
            
            # Build query with OR condition for all aliases
            filters = [ReportField.field_name.ilike(f"%{term}%") for term in search_terms]
            
            query = db.session.query(ReportField, Report.report_date).join(Report).filter(
                ReportField.user_id == current_user_id,
                or_(*filters)
            )
            
            if profile_id:
                query = query.filter(Report.profile_id == profile_id)
                
            fields = query.order_by(Report.report_date).all()
            
            if not fields:
                continue
                
            data_points = []
            for field, date in fields:
                # Try to clean value (handle "12.5 mg/dL" -> 12.5)
                try:
                    import re
                    numeric_match = re.search(r"[-+]?\d*\.\d+|\d+", field.field_value)
                    clean_value = float(numeric_match.group()) if numeric_match else field.field_value
                except:
                    clean_value = field.field_value
                    
                data_points.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'value': clean_value,
                    'raw_value': field.field_value,
                    'unit': field.field_unit,
                    'is_normal': field.is_normal,
                    'report_id': field.report_id
                })
            
            trends[name] = data_points
            
        return {'trends': trends}, 200


@reports_ns.route('/stats')
class TimelineStats(Resource):
    @reports_ns.doc(
        security='Bearer Auth',
        params={'profile_id': 'Optional: Filter stats by specific profile ID'}
    )
    @jwt_required()
    def get(self):
        """Get high-level statistics for the timeline header (optionally filtered by profile)"""
        current_user_id = int(get_jwt_identity())
        profile_id = request.args.get('profile_id')
        
        query = Report.query.filter_by(user_id=current_user_id)
        
        if profile_id:
            # Verify user owns this profile or has shared access
            profile = Profile.query.filter_by(id=profile_id, creator_id=current_user_id).first()
            
            if not profile:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    profile = Profile.query.get(profile_id)

            if not profile:
                return {'message': 'Invalid profile_id or unauthorized access'}, 403
            query = query.filter_by(profile_id=profile_id)
            
        total_reports = query.count()
        last_report = query.order_by(Report.report_date.desc()).first()
        
        # Calculate overall health status based on recent abnormal results
        health_status = "Good"
        if last_report:
            abnormal_count = ReportField.query.filter_by(report_id=last_report.id, is_normal=False).count()
            if abnormal_count > 0:
                health_status = "Attention Needed"
                
        return {
            'total_reports': total_reports,
            'last_checkup': last_report.report_date.strftime('%Y-%m-%d') if last_report else None,
            'health_status': health_status
        }, 200


@reports_ns.route('/<int:report_id>')
class UserReportDetail(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, report_id):
        """Get a specific report by ID"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.get(report_id)
        
        if not report:
            return {'message': 'Report not found'}, 404
            
        # Check access
        if report.user_id != current_user_id:
            # Check if shared
            has_access = False
            if report.profile_id:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=report.profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    has_access = True
            
            if not has_access:
                return {'message': 'Report not found or unauthorized access'}, 404
        
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
        
        # Get profile information
        profile_info = None
        if report.profile_id:
            profile = Profile.query.get(report.profile_id)
            if profile:
                profile_info = {
                    'id': profile.id,
                    'first_name': profile.first_name,
                    'last_name': profile.last_name,
                    'relationship': profile.relationship
                }
        
        return {
            'message': 'Report retrieved successfully',
            'report': {
                'report_id': report.id,
                'profile_id': report.profile_id,
                'profile': profile_info,
                'report_date': str(report.report_date),
                'report_name': report.report_name,
                'report_type': report.report_type,
                'patient_name': report.patient_name,
                'doctor_names': report.doctor_names,
                'patient_age': report.patient_age,
                'patient_gender': report.patient_gender,
                'created_at': str(report.created_at),
                'total_fields': len(fields_data),
                'total_images': len(images_info),
                'images': images_info,
                'fields': fields_data,
                'additional_fields': additional_fields_data
            }
        }, 200

    @reports_ns.doc(security='Bearer Auth', description='DELETE endpoint - FOR TESTING ONLY')
    @jwt_required()
    def delete(self, report_id):
        """Delete a specific report by ID - FOR TESTING PURPOSES ONLY"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        try:
            ReportField.query.filter_by(report_id=report_id).delete()
            AdditionalField.query.filter_by(report_id=report_id).delete()
            db.session.delete(report)
            db.session.commit()
            
            return {
                'message': 'Report deleted successfully (TESTING MODE)',
                'deleted_report_id': report_id
            }, 200
        except Exception as e:
            db.session.rollback()
            return {
                'message': 'Failed to delete report',
                'error': str(e)
            }, 500



@reports_ns.route('/<int:report_id>/categorized')
class ReportCategorized(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, report_id):
        """Get report data grouped by categories"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.get(report_id)
        
        if not report:
            return {'message': 'Report not found'}, 404
            
        # Check access
        if report.user_id != current_user_id:
            # Check if shared
            has_access = False
            if report.profile_id:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=report.profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    has_access = True
            
            if not has_access:
                return {'message': 'Report not found or unauthorized access'}, 404
        
        report_fields = ReportField.query.filter_by(report_id=report.id).order_by(ReportField.id).all()
        
        # Group by category
        categorized_data = defaultdict(list)
        
        for field in report_fields:
            category = field.category if field.category and field.category.strip() else "General"
            categorized_data[category].append({
                'id': field.id,
                'field_name': field.field_name,
                'field_value': field.field_value,
                'field_unit': field.field_unit,
                'normal_range': field.normal_range,
                'is_normal': field.is_normal,
                'field_type': field.field_type,
                'notes': field.notes
            })
            
        return {
            'report_id': report.id,
            'patient_name': f"{user.first_name} {user.last_name}", 
            'patient_age': report.patient_age,
            'patient_gender': report.patient_gender,
            'report_date': str(report.report_date),
            'report_name': report.report_name,
            'report_type': report.report_type,
            'doctor_names': report.doctor_names,
            'categories': categorized_data
        }, 200


@reports_ns.route('/<int:report_id>/images')
class ReportImages(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, report_id):
        """Get all uploaded image/PDF files associated with a specific report"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.get(report_id)
        
        if not report:
            return {'message': 'Report not found'}, 404
            
        # Check access
        if report.user_id != current_user_id:
            # Check if shared
            has_access = False
            if report.profile_id:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=report.profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    has_access = True
            
            if not has_access:
                return {'message': 'Report not found or unauthorized access'}, 404
        
        
        # Get all files for this report from database
        report_files = ReportFile.query.filter_by(report_id=report_id).order_by(ReportFile.id).all()
        
        if not report_files:
            return {'message': 'No files found for this report'}, 404
        
        files_list = []
        for idx, report_file in enumerate(report_files, 1):
            files_list.append({
                'index': idx,
                'filename': report_file.original_filename,
                'file_type': report_file.file_type,
                'download_url': f'/reports/{report_id}/images/{idx}'
            })
        
        return {
            'report_id': report_id,
            'total_files': len(files_list),
            'files': files_list
        }, 200


@reports_ns.route('/<int:report_id>/images/<int:image_index>')
class ReportImageByIndex(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, report_id, image_index):
        """
        Get a specific image/page by index for a report
        
        Note: This endpoint accepts the JWT token in the 'Authorization' header OR 
        in a query parameter named 'token' (e.g., ?token=eyJhbGciOi...) to support 
        direct access in <img> tags.
        """
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.get(report_id)
        
        if not report:
            return {'message': 'Report not found'}, 404
            
        # Check access
        if report.user_id != current_user_id:
            # Check if shared
            has_access = False
            if report.profile_id:
                from models import ProfileShare
                share = ProfileShare.query.filter_by(profile_id=report.profile_id, shared_with_user_id=current_user_id).first()
                if share:
                    has_access = True
            
            if not has_access:
                return {'message': 'Report not found or unauthorized access'}, 404
        
        
        # Get all files for this report from database
        report_files = ReportFile.query.filter_by(report_id=report_id).order_by(ReportFile.id).all()
        
        if not report_files:
            return {'message': 'No files found for this report'}, 404
        
        # Check if index is valid
        if image_index < 1 or image_index > len(report_files):
            return {'message': f'Invalid image index. Valid range: 1-{len(report_files)}'}, 404
        
        # Get the file at the specified index (1-based)
        report_file = report_files[image_index - 1]
        file_path = report_file.file_path
        
        if not os.path.exists(file_path):
            return {'message': 'File not found on disk'}, 404
        
        # Determine mimetype based on file extension
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'pdf': 'application/pdf'
        }
        mimetype = mimetype_map.get(report_file.file_type, 'application/octet-stream')
        
        return send_file(file_path, mimetype=mimetype, as_attachment=False)


@reports_ns.route('/delete-all')
class DeleteAllReports(Resource):
    @reports_ns.doc(
        security='Bearer Auth',
        description='DELETE ALL REPORTS - FOR TESTING ONLY - Requires admin password',
        params={'password': 'Admin password (testingAdmin)'}
    )
    @jwt_required()
    def delete(self):
        """Delete ALL reports for the current user - FOR TESTING PURPOSES ONLY"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        # Check for admin password in query parameters
        password = request.args.get('password')
        
        if password != 'testingAdmin':
            return {
                'message': 'Unauthorized - Invalid admin password',
                'hint': 'Use password=testingAdmin'
            }, 403
        
        try:
            # Get all reports for this user
            reports = Report.query.filter_by(user_id=current_user_id).all()
            report_count = len(reports)
            
            if report_count == 0:
                return {
                    'message': 'No reports to delete',
                    'deleted_count': 0
                }, 200
            
            # Delete all reports (cascade will handle ReportField, AdditionalField, and ReportFile)
            for report in reports:
                db.session.delete(report)
            
            db.session.commit()
            
            return {
                'message': f'Successfully deleted all reports for user (TESTING MODE)',
                'deleted_count': report_count,
                'user_id': current_user_id,
                'user_email': user.email
            }, 200
            
        except Exception as e:
            db.session.rollback()
            return {
                'message': 'Failed to delete reports',
                'error': str(e)
            }, 500
