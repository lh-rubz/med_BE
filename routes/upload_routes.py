from flask import request
from flask_restx import Resource, Namespace, fields
from werkzeug.datastructures import FileStorage

from utils.google_drive import upload_file_to_drive, delete_file_from_drive

# Create namespace
upload_ns = Namespace('upload', description='File upload operations (Testing)')

# API Models
upload_parser = upload_ns.parser()
upload_parser.add_argument('file', location='files', type=FileStorage, required=True, help='File to upload')
upload_parser.add_argument('admin_password', location='form', type=str, required=True, help='Admin password for testing')

delete_model = upload_ns.model('DeleteFile', {
    'file_id': fields.String(required=True, description='Google Drive file ID'),
    'admin_password': fields.String(required=True, description='Admin password for testing')
})


@upload_ns.route('/test-upload')
class TestUpload(Resource):
    @upload_ns.expect(upload_parser)
    def post(self):
        """Test file upload to Google Drive (Admin only)"""
        # Hardcoded admin password for testing
        ADMIN_PASSWORD = 'testingadmin'
        
        # Get form data
        args = upload_parser.parse_args()
        admin_password = args.get('admin_password')
        file = args.get('file')
        
        # Verify admin password
        if admin_password != ADMIN_PASSWORD:
            return {'message': 'Invalid admin password'}, 403
        
        if not file:
            return {'message': 'No file provided'}, 400
        
        try:
            # Read file data
            file_data = file.read()
            filename = file.filename
            mimetype = file.content_type or 'application/octet-stream'
            
            # Upload to Google Drive
            result = upload_file_to_drive(file_data, filename, mimetype)
            
            return {
                'message': 'File uploaded successfully to Google Drive',
                'file': result
            }, 200
            
        except Exception as e:
            return {
                'message': 'Failed to upload file to Google Drive',
                'error': str(e)
            }, 500


@upload_ns.route('/test-delete')
class TestDelete(Resource):
    @upload_ns.expect(delete_model)
    def post(self):
        """Test file deletion from Google Drive (Admin only)"""
        # Hardcoded admin password for testing
        ADMIN_PASSWORD = 'testingadmin'
        
        data = request.json
        admin_password = data.get('admin_password')
        file_id = data.get('file_id')
        
        # Verify admin password
        if admin_password != ADMIN_PASSWORD:
            return {'message': 'Invalid admin password'}, 403
        
        if not file_id:
            return {'message': 'File ID is required'}, 400
        
        try:
            success = delete_file_from_drive(file_id)
            
            if success:
                return {'message': 'File deleted successfully from Google Drive'}, 200
            else:
                return {'message': 'Failed to delete file'}, 500
                
        except Exception as e:
            return {
                'message': 'Failed to delete file from Google Drive',
                'error': str(e)
            }, 500
