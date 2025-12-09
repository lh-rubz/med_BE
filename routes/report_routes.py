from flask import request, send_file, jsonify
from flask_restx import Resource, Namespace
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import glob
from collections import defaultdict
from datetime import datetime

from models import db, User, Report, ReportField, AdditionalField, ReportFile
from config import Config
from utils.medical_mappings import get_search_terms
from sqlalchemy import or_

# Create namespace
reports_ns = Namespace('reports', description='Medical reports management')


@reports_ns.route('')
class UserReports(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get all extracted reports for the current user"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        reports = Report.query.filter_by(user_id=current_user_id).order_by(Report.created_at.desc()).all()
        
        if not reports:
            return {
                'message': 'No reports found',
                'total_reports': 0,
                'reports': []
            }, 200
        
        reports_data = []
        for report in reports:
            report_fields = ReportField.query.filter_by(report_id=report.id).all()
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
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get chronological timeline of reports with health summaries"""
        current_user_id = int(get_jwt_identity())
        
        # Get all reports ordered by date
        reports = Report.query.filter_by(user_id=current_user_id).order_by(Report.report_date.desc()).all()
        
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
    @reports_ns.doc(security='Bearer Auth', params={'field_name': 'Comma separated test names (e.g. Hemoglobin,WBC)'})
    @jwt_required()
    def get(self):
        """Get historical values for specific health metrics"""
        current_user_id = int(get_jwt_identity())
        field_names = request.args.get('field_name', '').split(',')
        
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
            
            fields = db.session.query(ReportField, Report.report_date).join(Report).filter(
                ReportField.user_id == current_user_id,
                or_(*filters)
            ).order_by(Report.report_date).all()
            
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
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get high-level statistics for the timeline header"""
        current_user_id = int(get_jwt_identity())
        
        total_reports = Report.query.filter_by(user_id=current_user_id).count()
        last_report = Report.query.filter_by(user_id=current_user_id).order_by(Report.report_date.desc()).first()
        
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
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        report_fields = ReportField.query.filter_by(report_id=report.id).all()
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
        
        return {
            'message': 'Report retrieved successfully',
            'report': {
                'report_id': report.id,
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
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        report_fields = ReportField.query.filter_by(report_id=report.id).all()
        
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
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        
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
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        
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
