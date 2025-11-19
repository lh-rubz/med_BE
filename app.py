from flask import Flask, request, jsonify
from flask_restx import Api, Resource, fields
from openai import OpenAI
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import hashlib
import json
import bcrypt
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Read configuration from .env file
def get_env(key, default=None):
    """Get environment variable with optional default"""
    value = os.getenv(key)
    if value is None and default is None:
        raise ValueError(f"Missing required environment variable: {key}")
    return value if value is not None else default

# ===== CONFIGURATION FROM .ENV =====
DATABASE_URL = get_env('DATABASE_URL')
SECRET_KEY = get_env('SECRET_KEY')
GEMMA_BASE_URL = get_env('GEMMA_BASE_URL', 'http://gemma-server:8051/v1')
if not GEMMA_BASE_URL.startswith('http'):
    GEMMA_BASE_URL = 'http://' + GEMMA_BASE_URL
GEMMA_MODEL_NAME = get_env('GEMMA_MODEL_NAME', 'local-gemma-3')
FLASK_HOST = get_env('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(get_env('FLASK_PORT', '8080'))
FLASK_DEBUG = get_env('FLASK_DEBUG', 'False').lower() == 'true'
# ====================================

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
app.config['JWT_SECRET_KEY'] = SECRET_KEY  # We'll use the same secret key for JWT
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(days=1)  # Token expires in 1 day
app.config['JWT_TOKEN_LOCATION'] = ['headers']
app.config['JWT_HEADER_NAME'] = 'Authorization'
app.config['JWT_HEADER_TYPE'] = 'Bearer'

# Initialize extensions
db = SQLAlchemy(app)
jwt = JWTManager(app)

# Define User model for medical application
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=False)
    phone_number = db.Column(db.String(20), nullable=False)
    medical_history = db.Column(db.Text)
    allergies = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    reports = db.relationship('Report', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_date = db.Column(db.DateTime, nullable=False)
    report_hash = db.Column(db.String(255), nullable=False)  # Hash to detect duplicates
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    fields = db.relationship('ReportField', backref='report', lazy=True, cascade='all, delete-orphan')


class ReportData(db.Model):
    """Deprecated - use ReportField instead"""
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    field_name = db.Column(db.String(120), nullable=False)
    field_value = db.Column(db.String(120), nullable=False)
    field_unit = db.Column(db.String(50))
    normal_range = db.Column(db.String(120))
    is_normal = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ReportField(db.Model):
    """Generic field storage for any medical data extracted from reports"""
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    field_name = db.Column(db.String(255), nullable=False)  # e.g., "Blood Pressure", "Weight", "Diagnosis"
    field_value = db.Column(db.Text, nullable=False)  # The actual value
    field_unit = db.Column(db.String(100))  # Optional unit (mmHg, kg, etc.)
    normal_range = db.Column(db.String(255))  # Optional normal range
    is_normal = db.Column(db.Boolean)  # Is this value normal?
    field_type = db.Column(db.String(50))  # 'measurement', 'diagnosis', 'medication', 'note', 'other'
    notes = db.Column(db.Text)  # Any additional notes
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AdditionalField(db.Model):
    """Track new fields that should be added to user profile"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    field_name = db.Column(db.String(120), nullable=False)
    field_value = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)  # 'medical_history', 'allergies', 'other'
    is_approved = db.Column(db.Boolean, default=False)
    approved_at = db.Column(db.DateTime)
    merged_to_profile = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

api = Api(app, version="1.0", title="Medical Application API",
          description="API for Medical Application with secure user management",
          doc="/swagger",
          authorizations={
              'Bearer Auth': {
                  'type': 'apiKey',
                  'in': 'header',
                  'name': 'Authorization',
                  'description': 'JWT Bearer token. Example: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...'
              }
          },
          security='Bearer Auth')

auth_ns = api.namespace('auth', description='Authentication operations')
user_ns = api.namespace('users', description='User operations')
vlm_ns = api.namespace('vlm', description='VLM and Report operations')
reports_ns = api.namespace('reports', description='Medical reports management')

# API Models
register_model = api.model('Registration', {
    'email': fields.String(required=True, description='User email address'),
    'password': fields.String(required=True, description='User password'),
    'first_name': fields.String(required=True, description='First name'),
    'last_name': fields.String(required=True, description='Last name'),
    'date_of_birth': fields.Date(required=True, description='Date of birth (YYYY-MM-DD)'),
    'phone_number': fields.String(required=True, description='Phone number'),
    'medical_history': fields.String(required=False, description='Medical history'),
    'allergies': fields.String(required=False, description='Allergies information')
})

login_model = api.model('Login', {
    'email': fields.String(required=True, description='User email address'),
    'password': fields.String(required=True, description='User password')
})

user_update_model = api.model('UserUpdate', {
    'first_name': fields.String(description='First name'),
    'last_name': fields.String(description='Last name'),
    'phone_number': fields.String(description='Phone number'),
    'medical_history': fields.String(description='Medical history'),
    'allergies': fields.String(description='Allergies information')
})

report_extraction_model = api.model('ReportExtraction', {
    'image_url': fields.String(required=True, description='URL to medical report image for extraction')
})


def create_client():
    """Create OpenAI-compatible client pointing at local Gemma-3 server"""
    client = OpenAI(
        base_url=GEMMA_BASE_URL,
        api_key="dummy-key",  # Local server doesn't need authentication
    )
    return client


@auth_ns.route('/register')
class Register(Resource):
    @auth_ns.expect(register_model)
    def post(self):
        """Register a new user"""
        data = request.json

        # Check if user already exists
        if User.query.filter_by(email=data['email']).first():
            return {'message': 'Email already registered'}, 409

        try:
            # Create new user
            new_user = User(
                email=data['email'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                date_of_birth=datetime.strptime(str(data['date_of_birth']), '%Y-%m-%d').date(),
                phone_number=data['phone_number'],
                medical_history=data.get('medical_history', ''),
                allergies=data.get('allergies', '')
            )
            new_user.set_password(data['password'])
            
            db.session.add(new_user)
            db.session.commit()

            return {'message': 'User registered successfully'}, 201
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

        access_token = create_access_token(identity=str(user.id))
        return {'access_token': access_token}, 200

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


@vlm_ns.route('/chat')
class ChatResource(Resource):
    @vlm_ns.doc(security='Bearer Auth')
    @jwt_required()
    @vlm_ns.expect(report_extraction_model)
    def post(self):
        """Extract medical report data and save to database"""
        current_user_id = int(get_jwt_identity())
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        data = request.json or {}
        image_url = data.get('image_url')
        
        if not image_url:
            return {'error': 'image_url is required for report extraction'}, 400

        client = create_client()

        # Step 0: Prepare minimal user data for VLM
        patient_name = user.first_name + " " + user.last_name
        
        # Step 1: Create lean VLM prompt (no test history to keep it short)
        extraction_prompt = f"""You are a medical lab report analyzer. Extract ALL medical data from this report.

USER NAME VERIFICATION:
Patient name must match: {patient_name}
- If name does NOT match, respond with ONLY: "NAME_MISMATCH"
- Otherwise proceed with extraction

EXTRACTION RULES:
1. Extract EVERY test result, measurement, value visible
2. For each result provide: test name, value, unit, normal range, if normal/abnormal
3. Extract report date if available

RESPONSE FORMAT - Return ONLY valid JSON:
{{
    "name_match": true,
    "patient_name": "{patient_name}",
    "report_date": "YYYY-MM-DD or empty",
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45",
            "field_unit": "g/dL",
            "normal_range": "13.5-17.5",
            "is_normal": true
        }}
    ]
}}

RULES:
- Response must be ONLY valid JSON
- Extract ALL visible fields
- medical_data array can be empty if none found
- Use empty strings for missing values
- is_normal: false if abnormal or outside range"""

        # Build message content
        content = [
            {
                'type': 'text',
                'text': extraction_prompt
            },
            {
                'type': 'image_url',
                'image_url': {'url': image_url}
            }
        ]

        try:
            completion = client.chat.completions.create(
                model=GEMMA_MODEL_NAME,  # Using local Gemma-3 model
                messages=[
                    {
                        'role': 'user',
                        'content': content
                    }
                ],
                temperature=0.1,  # Very low temperature for strict JSON output
                max_tokens=1024,  # Limit response length
            )

            response_text = completion.choices[0].message.content.strip()
            print("\n" + "="*80)
            print("🔍 VLM RAW RESPONSE:")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")
            
            # Step 2: Check if name matched
            if "NAME_MISMATCH" in response_text.upper():
                print("❌ NAME MISMATCH DETECTED - Report does not belong to this user")
                return {
                    'message': 'Patient name in report does not match your profile',
                    'error': 'Name mismatch',
                    'user_profile': patient_name
                }, 400
            
            # Step 3: Parse the extracted data
            extracted_data = None
            try:
                extracted_data = json.loads(response_text)
                print("\n" + "="*80)
                print("✅ PARSED JSON DATA:")
                print("="*80)
                print(json.dumps(extracted_data, indent=2))
                print("="*80 + "\n")
            except json.JSONDecodeError as e:
                print("\n" + "="*80)
                print("❌ JSON PARSE ERROR:")
                print("="*80)
                print(f"Error: {e}")
                print(f"Response was: {response_text[:200]}...")
                print("="*80 + "\n")
                
                # Try to extract JSON from response if it has extra text
                import re
                json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
                if json_match:
                    try:
                        extracted_data = json.loads(json_match.group())
                        print("✅ JSON extracted from response after regex match")
                    except:
                        extracted_data = None
                
                if not extracted_data:
                    print("❌ Could not parse VLM response as JSON - aborting extraction")
                    return {
                        'message': 'Failed to parse medical report',
                        'error': 'Invalid response format',
                        'details': f'JSON parse error: {str(e)}'
                    }, 400
            
            # Validate structure
            if not isinstance(extracted_data, dict):
                print("❌ Invalid response structure - not a dictionary")
                return {
                    'message': 'Failed to parse medical report',
                    'error': 'Invalid response structure'
                }, 400
            
            # Ensure required fields exist
            if 'name_match' not in extracted_data:
                extracted_data['name_match'] = True
            if 'medical_data' not in extracted_data:
                extracted_data['medical_data'] = []
            if 'patient_name' not in extracted_data:
                extracted_data['patient_name'] = patient_name
            
            # Final name verification
            if not extracted_data.get('name_match', False):
                print("❌ VLM name verification failed")
                return {
                    'message': 'Patient name in report does not match your profile',
                    'error': 'Name mismatch',
                    'reported_name': extracted_data.get('patient_name'),
                    'your_name': patient_name
                }, 400
            
            # Step 4: Enhanced duplicate detection - compare extracted data
            medical_data_list = extracted_data.get('medical_data', [])
            
            if len(medical_data_list) > 0:
                # Get all existing reports for this user
                existing_reports = Report.query.filter_by(user_id=current_user_id).all()
                
                print("\n" + "="*80)
                print("🔍 CHECKING FOR DUPLICATES:")
                print("="*80)
                print(f"New report has {len(medical_data_list)} fields")
                print(f"Comparing against {len(existing_reports)} existing reports...\n")
                
                # Create a set of field names and values from new report
                new_field_map = {}
                for item in medical_data_list:
                    field_name = str(item.get('field_name', '')).lower().strip()
                    field_value = str(item.get('field_value', '')).strip()
                    new_field_map[field_name] = field_value
                
                # Check each existing report
                for existing_report in existing_reports:
                    existing_fields = ReportField.query.filter_by(report_id=existing_report.id).all()
                    existing_field_map = {}
                    for field in existing_fields:
                        field_name = str(field.field_name).lower().strip()
                        field_value = str(field.field_value).strip()
                        existing_field_map[field_name] = field_value
                    
                    # Calculate match percentage
                    if existing_field_map:
                        matching_fields = 0
                        for field_name, field_value in new_field_map.items():
                            if field_name in existing_field_map and existing_field_map[field_name] == field_value:
                                matching_fields += 1
                        
                        match_percentage = (matching_fields / len(new_field_map)) * 100 if new_field_map else 0
                        
                        print(f"Report #{existing_report.id}: {match_percentage:.1f}% match ({matching_fields}/{len(new_field_map)} fields)")
                        
                        # If 90% or more fields match, it's likely a duplicate
                        if match_percentage >= 90:
                            print(f"⚠️  HIGH MATCH DETECTED ({match_percentage:.1f}%)")
                            return {
                                'message': 'This report appears to be a duplicate of an existing report',
                                'error': 'Possible duplicate',
                                'existing_report_id': existing_report.id,
                                'existing_report_date': str(existing_report.created_at),
                                'match_percentage': match_percentage,
                                'matching_fields': matching_fields,
                                'total_new_fields': len(new_field_map)
                            }, 409
                
                print("✅ No duplicates found - Report is unique\n")
                print("="*80 + "\n")
            
            # Step 5: Create new report
            try:
                # Create hash based on medical data for record keeping
                medical_data_str = json.dumps(medical_data_list, sort_keys=True)
                report_hash = hashlib.sha256(medical_data_str.encode()).hexdigest()
                
                new_report = Report(
                    user_id=current_user_id,
                    report_date=datetime.utcnow(),
                    report_hash=report_hash
                )
                db.session.add(new_report)
                db.session.flush()  # Flush to get the report ID
                
                # Step 6: Add ALL extracted fields to ReportField table
                medical_entries = []
                
                print("\n" + "="*80)
                print(f"📊 PROCESSING {len(medical_data_list)} MEDICAL FIELDS:")
                print("="*80)
                
                for i, item in enumerate(medical_data_list):
                    print(f"\n[Field {i+1}]:")
                    print(json.dumps(item, indent=2))
                    
                    # Ensure item is a dict
                    if not isinstance(item, dict):
                        print(f"⚠️  Skipping non-dict item: {item}")
                        continue
                    
                    field = ReportField(
                        report_id=new_report.id,
                        user_id=current_user_id,
                        field_name=str(item.get('field_name', 'Unknown')),
                        field_value=str(item.get('field_value', '')),
                        field_unit=str(item.get('field_unit', '')),
                        normal_range=str(item.get('normal_range', '')),
                        is_normal=bool(item.get('is_normal', True)),
                        field_type=str(item.get('field_type', 'measurement')),
                        notes=str(item.get('notes', ''))
                    )
                    db.session.add(field)
                    db.session.flush()  # Flush to get the field ID
                    
                    medical_entries.append({
                        'id': field.id,
                        'field_name': field.field_name,
                        'field_value': field.field_value,
                        'field_unit': field.field_unit,
                        'normal_range': field.normal_range,
                        'is_normal': field.is_normal,
                        'field_type': field.field_type,
                        'notes': field.notes
                    })
                
                print("="*80)
                print(f"✅ Successfully added {len(medical_entries)} fields to database")
                print("="*80 + "\n")
                
                # Commit all changes
                db.session.commit()
                
                return {
                    'message': 'Report extracted and saved successfully',
                    'report_id': new_report.id,
                    'patient_name': extracted_data.get('patient_name', ''),
                    'report_date': extracted_data.get('report_date', ''),
                    'medical_data': medical_entries,
                    'total_fields_extracted': len(medical_entries)
                }, 201
                
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ ERROR saving to database: {str(e)}")
                import traceback
                traceback.print_exc()
                return {
                    'message': 'Failed to save report data',
                    'error': str(e)
                }, 500
                
        except Exception as e:
            print(f"\n❌ VLM PROCESSING ERROR: {str(e)}")
            import traceback
            traceback.print_exc()
            return {'error': f'VLM processing error: {str(e)}'}, 500


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
            # Get all fields for this report
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
            
            # Get additional fields for this report
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
            
            reports_data.append({
                'report_id': report.id,
                'report_date': str(report.report_date),
                'created_at': str(report.created_at),
                'total_fields': len(fields_data),
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
        
        # Get all fields for this report
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
        
        # Get additional fields for this report
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
        
        return {
            'message': 'Report retrieved successfully',
            'report': {
                'report_id': report.id,
                'report_date': str(report.report_date),
                'created_at': str(report.created_at),
                'total_fields': len(fields_data),
                'fields': fields_data,
                'additional_fields': additional_fields_data
            }
        }, 200


@reports_ns.route('/<int:report_id>')
class DeleteReportDetail(Resource):
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
            # Delete all fields associated with this report
            ReportField.query.filter_by(report_id=report_id).delete()
            
            # Delete all additional fields associated with this report
            AdditionalField.query.filter_by(report_id=report_id).delete()
            
            # Delete the report itself
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




def init_db():
    with app.app_context():
        try:
            # Create all database tables
            db.create_all()
            print("Database tables created successfully!")
        except Exception as e:
            print(f"Database initialization warning: {e}")
            print("App will run in read-only mode. Please verify PostgreSQL connection.")

if __name__ == '__main__':
    # Initialize the database
    init_db()
    print("\n✅ Starting Medical Application API...")
    print("⚠️  IMPORTANT: Make sure Gemma-3 server is running on port 8051")
    print("   Run in another terminal: python gemma3.py")
    print(f"\n📚 Swagger documentation available at: http://localhost:{FLASK_PORT}/swagger")
    print("🔐 API Routes by Namespace:")
    print("\n📋 Authentication (auth/)")
    print("   - POST /auth/register - Register new user")
    print("   - POST /auth/login - Login and get JWT token")
    print("\n👤 Users (users/)")
    print("   - GET /users/profile - Get user profile (requires JWT)")
    print("   - PUT /users/profile - Update user profile (requires JWT)")
    print("\n🔬 VLM Operations (vlm/)")
    print("   - POST /vlm/chat - Extract medical report data from image (requires JWT)")
    print("\n📊 Reports Management (reports/)")
    print("   - GET /reports - Get all user reports with extracted data (requires JWT)")
    print("   - GET /reports/<id> - Get a specific report by ID (requires JWT)")
    print("   - DELETE /reports/<id> - Delete a report by ID (requires JWT) [FOR TESTING ONLY]")
    print("\n🤖 Model Configuration:")
    print(f"   - Base URL: {GEMMA_BASE_URL}")
    print(f"   - Model: {GEMMA_MODEL_NAME}")
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=FLASK_PORT)