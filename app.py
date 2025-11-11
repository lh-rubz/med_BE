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

# Load environment variables from .env file FIRST
load_dotenv()

# NOTE: token is hardcoded as requested by the user. For production, use environment variables.
HF_TOKEN = "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"

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['JWT_SECRET_KEY'] = os.getenv('SECRET_KEY')  # We'll use the same secret key for JWT
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

prompt_model = api.model('Prompt', {
    'prompt': fields.String(required=True, description='Text prompt to send to the model'),
    'image_url': fields.String(required=False, description='Optional image URL')
})


def create_client(require_image_support: bool = False):
    import requests

    local_server = os.getenv("LOCAL_GEMMA_URL", "http://localhost:8051")
    try:
        response = requests.get(f"{local_server}/health", timeout=2)
        if response.status_code == 200:
            payload = response.json()
            supports_images = bool(payload.get("supports_images", False))
            if not require_image_support or supports_images:
                print("✅ Using LOCAL Gemma3 model server on port 8051")
                client = OpenAI(
                    base_url=f"{local_server}/v1",
                    api_key="no-key-needed-for-local",
                )
                return client, supports_images
            print("ℹ️ Local Gemma3 server is text-only. Falling back to HuggingFace for image support.")
    except Exception as exc:
        print(f"ℹ️ Local Gemma3 server unavailable: {exc}")

    print("⚠️ Using HuggingFace router as fallback.")
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HF_TOKEN,
    )
    return client, True


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
    @vlm_ns.expect(prompt_model)
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

        client, _ = create_client(require_image_support=bool(image_url))

        # Step 1: Extract user name from report
        patient_name = user.first_name + " " + user.last_name
        
        extraction_prompt = f"""You are a medical lab report analyzer. Your task is to extract ALL medical data from this lab report image.

CRITICAL INSTRUCTIONS:
1. First, verify the patient name matches: {patient_name}
   - If the name does NOT match, respond with only: "NAME_MISMATCH"
   - If it DOES match or no name is visible, proceed to step 2

2. Extract EVERY single test result, measurement, or data point visible in the report, including:
   - Test names (e.g., Hemoglobin, WBC, RBC, Platelet Count, etc.)
   - Values (the actual numbers)
   - Units (mmol/L, g/dL, 10^3/µL, etc.)
   - Reference ranges (normal values shown)
   - Whether it's abnormal (marked with up arrow or down arrow or outside reference range)

3. Look for ANY numbers, measurements, or values on the report - extract them ALL

4. Extract any notable findings, impressions, or diagnoses if present

RESPONSE FORMAT - Return ONLY valid JSON with NO extra text. Example structure:
{{
    "name_match": true,
    "patient_name": "Full Name from report or user name",
    "report_date": "Date from report or empty string",
    "medical_data": [
        {{
            "field_name": "Test Name",
            "field_value": "123.45",
            "field_unit": "g/dL",
            "normal_range": "13.5-17.5",
            "is_normal": false
        }}
    ],
    "findings": "Any notes or findings from the report"
}}

IMPORTANT RULES:
- ALWAYS respond with ONLY the JSON, never add explanation
- Extract EVERY field visible on the report
- If no data found, medical_data should be an empty array
- Use empty strings for missing values, never use null
- is_normal should be false if value is outside reference range or marked abnormal
- medical_data array MUST contain all extracted test results"""

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
                model="google/gemma-3-12b-it",
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
            print("🔍 VLM RAW RESPONSE:")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")
            
            # Remove markdown code blocks if present
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            # Step 2: Check if name matched
            if "NAME_MISMATCH" in response_text.upper():
                return {
                    'message': 'Patient name in report does not match your profile',
                    'error': 'Name mismatch'
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
                    extracted_data = {
                        'name_match': True,
                        'patient_name': user.first_name + ' ' + user.last_name,
                        'report_date': '',
                        'medical_data': [],
                        'findings': f'Failed to parse VLM response: {e}'
                    }
                    print("[Fallback data created]\n")
            
            # Validate structure
            if not isinstance(extracted_data, dict):
                extracted_data = {
                    'name_match': True,
                    'patient_name': user.first_name + ' ' + user.last_name,
                    'report_date': '',
                    'medical_data': [],
                    'findings': 'Invalid response structure'
                }
            
            # Ensure required fields exist
            if 'name_match' not in extracted_data:
                extracted_data['name_match'] = True
            if 'medical_data' not in extracted_data:
                extracted_data['medical_data'] = []
            if 'patient_name' not in extracted_data:
                extracted_data['patient_name'] = user.first_name + ' ' + user.last_name
            
            if not extracted_data.get('name_match', False):
                return {
                    'message': 'Patient name in report does not match your profile',
                    'error': 'Name mismatch'
                }, 400
            
            # Step 4: Check for duplicate reports
            medical_data_str = json.dumps(extracted_data.get('medical_data', []), sort_keys=True)
            report_hash = hashlib.sha256(medical_data_str.encode()).hexdigest()
            
            existing_report = Report.query.filter_by(
                user_id=current_user_id,
                report_hash=report_hash
            ).first()
            
            if existing_report and len(extracted_data.get('medical_data', [])) > 0:
                return {
                    'message': 'You have already extracted this report',
                    'error': 'Duplicate report',
                    'existing_report_id': existing_report.id,
                    'existing_report_date': str(existing_report.created_at)
                }, 409
            
            # Step 5: Create new report
            try:
                new_report = Report(
                    user_id=current_user_id,
                    report_date=datetime.utcnow(),
                    report_hash=report_hash
                )
                db.session.add(new_report)
                db.session.flush()  # Flush to get the report ID
                
                # Step 6: Add ALL extracted fields to ReportField table
                medical_entries = []
                medical_data_list = extracted_data.get('medical_data', [])
                
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
    print("📚 Swagger documentation available at: http://localhost:5000/swagger")
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
    app.run(debug=True, host='0.0.0.0', port=5000)
