from flask import request, send_file, jsonify
from flask_restx import Resource, Namespace
from flask_jwt_extended import jwt_required, get_jwt_identity
import os
import glob

from models import db, User, Report, ReportField, AdditionalField
from config import Config

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
            
            # Get images info for this report
            user_folder = os.path.join(Config.UPLOAD_FOLDER, f"user_{current_user_id}")
            images_info = []
            
            if os.path.exists(user_folder) and report.original_filename:
                pattern = os.path.join(user_folder, f"*{report.original_filename}")
                matching_files = glob.glob(pattern)
                
                # Also look for files created within a 5-minute window
                all_files = glob.glob(os.path.join(user_folder, "*"))
                report_timestamp = report.created_at
                
                for file_path in all_files:
                    if file_path in matching_files:
                        continue
                    
                    file_mtime = os.path.getmtime(file_path)
                    from datetime import datetime, timezone
                    file_datetime = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
                    time_diff = abs((report_timestamp - file_datetime).total_seconds())
                    
                    if time_diff <= 300:
                        matching_files.append(file_path)
                
                matching_files.sort()
                
                for idx, file_path in enumerate(matching_files, 1):
                    filename = os.path.basename(file_path)
                    file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                    images_info.append({
                        'index': idx,
                        'filename': filename,
                        'file_type': file_extension,
                        'url': f'/reports/{report.id}/images/{idx}'
                    })
            
            reports_data.append({
                'report_id': report.id,
                'report_date': str(report.report_date),
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
        
        # Get images info for this report
        user_folder = os.path.join(Config.UPLOAD_FOLDER, f"user_{current_user_id}")
        images_info = []
        
        if os.path.exists(user_folder) and report.original_filename:
            pattern = os.path.join(user_folder, f"*{report.original_filename}")
            matching_files = glob.glob(pattern)
            
            # Also look for files created within a 5-minute window
            all_files = glob.glob(os.path.join(user_folder, "*"))
            report_timestamp = report.created_at
            
            for file_path in all_files:
                if file_path in matching_files:
                    continue
                
                file_mtime = os.path.getmtime(file_path)
                from datetime import datetime, timezone
                file_datetime = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
                time_diff = abs((report_timestamp - file_datetime).total_seconds())
                
                if time_diff <= 300:
                    matching_files.append(file_path)
            
            matching_files.sort()
            
            for idx, file_path in enumerate(matching_files, 1):
                filename = os.path.basename(file_path)
                file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                images_info.append({
                    'index': idx,
                    'filename': filename,
                    'file_type': file_extension,
                    'url': f'/reports/{report.id}/images/{idx}'
                })
        
        return {
            'message': 'Report retrieved successfully',
            'report': {
                'report_id': report.id,
                'report_date': str(report.report_date),
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
        
        # Get user folder
        user_folder = os.path.join(Config.UPLOAD_FOLDER, f"user_{current_user_id}")
        
        if not os.path.exists(user_folder):
            return {'message': 'No files found for this report'}, 404
        
        # Find all files that could belong to this report
        report_files = []
        
        if report.original_filename:
            # Find all files that end with this filename (accounting for timestamp prefix)
            pattern = os.path.join(user_folder, f"*{report.original_filename}")
            matching_files = glob.glob(pattern)
            
            # Also look for files created within a 5-minute window of the report
            all_files = glob.glob(os.path.join(user_folder, "*"))
            report_timestamp = report.created_at
            
            for file_path in all_files:
                if file_path in matching_files:
                    continue
                    
                # Check file modification time is close to report creation time
                file_mtime = os.path.getmtime(file_path)
                from datetime import datetime, timezone
                file_datetime = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
                time_diff = abs((report_timestamp - file_datetime).total_seconds())
                
                # If file was created within 5 minutes of report, include it
                if time_diff <= 300:  # 5 minutes = 300 seconds
                    matching_files.append(file_path)
            
            # Sort by filename to ensure consistent ordering
            matching_files.sort()
            
            for idx, file_path in enumerate(matching_files, 1):
                filename = os.path.basename(file_path)
                file_extension = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
                
                report_files.append({
                    'index': idx,
                    'filename': filename,
                    'file_type': file_extension,
                    'download_url': f'/reports/{report_id}/images/{idx}'
                })
        
        if not report_files:
            return {'message': 'No files found for this report'}, 404
        
        return {
            'report_id': report_id,
            'total_files': len(report_files),
            'files': report_files
        }, 200


@reports_ns.route('/<int:report_id>/images/<int:image_index>')
class ReportImageByIndex(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self, report_id, image_index):
        """Get a specific image/page by index for a report"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        report = Report.query.filter_by(id=report_id, user_id=current_user_id).first()
        
        if not report:
            return {'message': 'Report not found'}, 404
        
        # Get user folder
        user_folder = os.path.join(Config.UPLOAD_FOLDER, f"user_{current_user_id}")
        
        if not os.path.exists(user_folder):
            return {'message': 'No files found for this report'}, 404
        
        # Find all files that could belong to this report
        matching_files = []
        
        if report.original_filename:
            # Find all files that end with this filename
            pattern = os.path.join(user_folder, f"*{report.original_filename}")
            matching_files = glob.glob(pattern)
            
            # Also look for files created within a 5-minute window
            all_files = glob.glob(os.path.join(user_folder, "*"))
            report_timestamp = report.created_at
            
            for file_path in all_files:
                if file_path in matching_files:
                    continue
                    
                file_mtime = os.path.getmtime(file_path)
                from datetime import datetime, timezone
                file_datetime = datetime.fromtimestamp(file_mtime, tz=timezone.utc)
                time_diff = abs((report_timestamp - file_datetime).total_seconds())
                
                if time_diff <= 300:
                    matching_files.append(file_path)
            
            # Sort by filename to ensure consistent ordering
            matching_files.sort()
        
        if not matching_files:
            return {'message': 'No files found for this report'}, 404
        
        # Check if index is valid
        if image_index < 1 or image_index > len(matching_files):
            return {'message': f'Invalid image index. Valid range: 1-{len(matching_files)}'}, 404
        
        # Get the file at the specified index (1-based)
        file_path = matching_files[image_index - 1]
        
        if not os.path.exists(file_path):
            return {'message': 'File not found'}, 404
        
        # Determine mimetype based on file extension
        file_extension = file_path.rsplit('.', 1)[1].lower()
        mimetype_map = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'gif': 'image/gif',
            'webp': 'image/webp',
            'pdf': 'application/pdf'
        }
        mimetype = mimetype_map.get(file_extension, 'application/octet-stream')
        
        return send_file(file_path, mimetype=mimetype, as_attachment=False)

