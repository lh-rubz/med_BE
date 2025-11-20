from flask import Flask, request, jsonify
from flask_restx import Api, Resource, fields
import requests  # We'll use the 'requests' library to talk to our new model server.
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
import hashlib
import json
import base64
import bcrypt
import os
from dotenv import load_dotenv
from openai import OpenAI
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

# Load environment variables from .env file
load_dotenv()

# Configure NO_PROXY to exclude localhost from proxy (important for local VLM server)
# This prevents proxy from blocking localhost connections
no_proxy = os.environ.get('NO_PROXY', '')
no_proxy_list = [item.strip() for item in no_proxy.split(',') if item.strip()]
no_proxy_list.extend(['localhost', '127.0.0.1', '0.0.0.0', '::1', 'localhost:11434', '127.0.0.1:11434'])
os.environ['NO_PROXY'] = ','.join(set(no_proxy_list))

# Temporarily unset proxy env vars before creating httpx client to ensure localhost bypasses proxy
# Store original values to restore after httpx client creation (needed for external image downloads)
_original_proxy_vars = {}
for var in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
    if var in os.environ:
        _original_proxy_vars[var] = os.environ.pop(var)

app = Flask(__name__)
# Get database URL and secret key from environment variables
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://user:user@localhost/meddb')
SECRET_KEY = os.getenv('SECRET_KEY', 'MedicalApp@2025SecureKey123')

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
    # create OpenAI-compatible client pointing at Ollama server
    # Ollama provides OpenAI-compatible API at /v1 endpoint
    ollama_url = os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434/v1')
    
    # Create a custom HTTP client that bypasses proxy for localhost
    # This is necessary because some proxy configurations block localhost
    # Explicitly disable all proxies to bypass Squid proxy blocking localhost
    client_kwargs = {
        'base_url': ollama_url,
        'api_key': 'not-needed',
    }
    
    if HAS_HTTPX:
        # Use httpx client - NO_PROXY env var should prevent proxy usage for localhost
        # httpx respects NO_PROXY environment variable
        http_client = httpx.Client(
            timeout=600.0,  # Long timeout for VLM processing
        )
        client_kwargs['http_client'] = http_client
    else:
        # Fallback: rely on NO_PROXY environment variable
        # Note: This may not work if the library doesn't respect NO_PROXY
        pass
    
    client = OpenAI(**client_kwargs)
    return client

client = create_client()

# Restore proxy environment variables after httpx client creation
# This allows requests library to use proxy for external image downloads
# while httpx client (already created) will bypass proxy for localhost via NO_PROXY
for var, value in _original_proxy_vars.items():
    os.environ[var] = value


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

        # Download and convert image to base64 for Ollama
        # Ollama vision models require base64-encoded images, not URLs
        try:
            # Download the image using proxy (proxy env vars are restored)
            # Create a session with proxy support for external URLs
            session = requests.Session()
            # Proxy will be used automatically from environment variables
            img_response = session.get(image_url, timeout=60)
            img_response.raise_for_status()
            
            # Convert to base64
            image_base64 = base64.b64encode(img_response.content).decode('utf-8')
            
            # Determine image format from content type or URL
            content_type = img_response.headers.get('Content-Type', '')
            if 'jpeg' in content_type or 'jpg' in content_type or image_url.lower().endswith(('.jpg', '.jpeg')):
                image_format = 'jpeg'
            elif 'png' in content_type or image_url.lower().endswith('.png'):
                image_format = 'png'
            elif 'webp' in content_type or image_url.lower().endswith('.webp'):
                image_format = 'webp'
            else:
                # Try to detect from image data
                from io import BytesIO
                from PIL import Image
                img = Image.open(BytesIO(img_response.content))
                image_format = img.format.lower() if img.format else 'jpeg'
            
            # Build message content with base64 image
            content = [
                {
                    'type': 'text',
                    'text': extraction_prompt
                },
                {
                    'type': 'image_url',
                    'image_url': {
                        'url': f'data:image/{image_format};base64,{image_base64}'
                    }
                }
            ]
        except Exception as e:
            print(f"\n❌ ERROR downloading/processing image: {str(e)}")
            return {
                'message': 'Failed to download or process image',
                'error': str(e)
            }, 400

        try:
            # Get model name from environment or use default
            model_name = os.getenv('OLLAMA_MODEL', 'gemma3:4b')
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        'role': 'user',
                        'content': content
                    }
                ],
                temperature=0.1,  # Very low temperature for strict JSON output
            )

            response_text = completion.choices[0].message.content.strip()
            print("\n" + "="*80)
            print("ðŸ” MODEL SERVER RAW RESPONSE:")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")
            
            # Step 2: Check if name matched
            if "NAME_MISMATCH" in response_text.upper():
                print("âŒ NAME MISMATCH DETECTED - Report does not belong to this user")
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
                print("âœ… PARSED JSON DATA:")
                print("="*80)
                print(json.dumps(extracted_data, indent=2))
                print("="*80 + "\n")
            except json.JSONDecodeError as e:
                print("\n" + "="*80)
                print("âŒ JSON PARSE ERROR:")
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
                        print("âœ… JSON extracted from response after regex match")
                    except:
                        extracted_data = None
                
                if not extracted_data:
                    print("âŒ Could not parse VLM response as JSON - aborting extraction")
                    return {
                        'message': 'Failed to parse medical report',
                        'error': 'Invalid response format',
                        'details': f'JSON parse error: {str(e)}'
                    }, 400
            
            # Validate structure
            if not isinstance(extracted_data, dict):
                print("âŒ Invalid response structure - not a dictionary")
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
                print("âŒ VLM name verification failed")
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
                print("ðŸ” CHECKING FOR DUPLICATES:")
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
                            print(f"âš ï¸  HIGH MATCH DETECTED ({match_percentage:.1f}%)")
                            return {
                                'message': 'This report appears to be a duplicate of an existing report',
                                'error': 'Possible duplicate',
                                'existing_report_id': existing_report.id,
                                'existing_report_date': str(existing_report.created_at),
                                'match_percentage': match_percentage,
                                'matching_fields': matching_fields,
                                'total_new_fields': len(new_field_map)
                            }, 409
                
                print("âœ… No duplicates found - Report is unique\n")
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
                print(f"ðŸ“Š PROCESSING {len(medical_data_list)} MEDICAL FIELDS:")
                print("="*80)
                
                for i, item in enumerate(medical_data_list):
                    print(f"\n[Field {i+1}]:")
                    print(json.dumps(item, indent=2))
                    
                    # Ensure item is a dict
                    if not isinstance(item, dict):
                        print(f"âš ï¸  Skipping non-dict item: {item}")
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
                print(f"âœ… Successfully added {len(medical_entries)} fields to database")
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
                print(f"\nâŒ ERROR saving to database: {str(e)}")
                import traceback
                traceback.print_exc()
                return {
                    'message': 'Failed to save report data',
                    'error': str(e)
                }, 500
                
        except Exception as e:
            print(f"\nâŒ VLM PROCESSING ERROR: {str(e)}")
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
    print("\nâœ… Starting Medical Application API...")
    print("ðŸ“š Swagger documentation available at: http://localhost:5000/swagger")
    print("ðŸ” API Routes by Namespace:")
    print("\nðŸ“‹ Authentication (auth/)")
    print("   - POST /auth/register - Register new user")
    print("   - POST /auth/login - Login and get JWT token")
    print("\nðŸ‘¤ Users (users/)")
    print("   - GET /users/profile - Get user profile (requires JWT)")
    print("   - PUT /users/profile - Update user profile (requires JWT)")
    print("\nðŸ”¬ VLM Operations (vlm/)")
    print("   - POST /vlm/chat - Extract medical report data from image (requires JWT)")
    print("\nðŸ“Š Reports Management (reports/)")
    print("   - GET /reports - Get all user reports with extracted data (requires JWT)")
    print("   - GET /reports/<id> - Get a specific report by ID (requires JWT)")
    print("   - DELETE /reports/<id> - Delete a report by ID (requires JWT) [FOR TESTING ONLY]")
    app.run(debug=True, host='0.0.0.0', port=8051)