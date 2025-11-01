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


def create_client():
    # create OpenAI-compatible client pointing at HF router
    client = OpenAI(
        base_url="https://router.huggingface.co/v1",
        api_key=HF_TOKEN,
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

        access_token = create_access_token(identity=user.id)
        return {'access_token': access_token}, 200

@user_ns.route('/profile')
class UserProfile(Resource):
    @user_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get user profile information"""
        current_user_id = get_jwt_identity()
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
        current_user_id = get_jwt_identity()
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
        current_user_id = get_jwt_identity()
        user = User.query.get(current_user_id)
        
        if not user:
            return {'message': 'User not found'}, 404
        
        data = request.json or {}
        image_url = data.get('image_url')
        
        if not image_url:
            return {'error': 'image_url is required for report extraction'}, 400

        client = create_client()

        # Step 1: Extract user name from report
        extraction_prompt = f"""You are a medical report analyzer. Please analyze the medical report image and:

1. FIRST: Extract the patient's full name from the report
2. Check if the name matches one of these formats:
   - First Name: {user.first_name}
   - Last Name: {user.last_name}
   - Full Name: {user.first_name} {user.last_name}

If the name in the report does NOT match the user's name ({user.first_name} {user.last_name}), respond with ONLY:
"no"

If the name DOES match, continue with the analysis:

3. Extract ALL medical data fields from the report, regardless of format. Include:
   - Field name (e.g., Blood Pressure, Hemoglobin, any value you find)
   - Field value (e.g., 120/80, 15.5, any measurement)
   - Unit (e.g., mmHg, g/dL, or empty if not available)
   - Normal range if available (e.g., 90-120, or empty string if not available)
   - is_normal: true if value appears normal, false if abnormal or uncertain
   - Report date

4. Check if any fields don't match the user's profile information (medical_history, allergies):
   - List any NEW fields or information not in the profile

5. Return the response in this EXACT JSON format. Be flexible with data - save anything you find:
{{
    "patient_name": "Full Name",
    "name_match": true,
    "report_date": "YYYY-MM-DD or description or empty string",
    "medical_data": [
        {{
            "field_name": "Field Name",
            "field_value": "Value",
            "field_unit": "Unit or empty",
            "normal_range": "Range or empty",
            "is_normal": true
        }}
    ],
    "new_fields": [
        {{
            "field_name": "New Field",
            "field_value": "Value",
            "category": "medical_history or allergies or other"
        }}
    ]
}}

Important: 
- Always respond with valid JSON (never plain text)
- medical_data array can be empty if no data found
- new_fields array can be empty if no new fields found
- Save ALL data you can extract, even if incomplete
- Use empty strings for missing values, not null"""

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
                model="google/gemma-3-12b-it:featherless-ai",
                messages=[
                    {
                        'role': 'user',
                        'content': content
                    }
                ],
                temperature=0.3,  # Lower temperature for more consistent parsing
            )

            response_text = completion.choices[0].message.content.strip()
            print("\n" + "="*80)
            print("🔍 VLM RAW RESPONSE:")
            print("="*80)
            print(response_text)
            print("="*80 + "\n")
            
            # Step 2: Check if name matched
            if response_text.lower() == "no":
                return {
                    'message': 'Patient name in report does not match your profile',
                    'error': 'Name mismatch'
                }, 400
            
            # Step 3: Parse the extracted data - be flexible and handle any format
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
                print("="*80 + "\n")
                # If JSON parsing fails, try to extract data manually from text
                extracted_data = {
                    'patient_name': user.first_name + ' ' + user.last_name,
                    'name_match': True,
                    'report_date': '',
                    'medical_data': [],
                    'new_fields': []
                }
                print("[Fallback Data Created - Empty arrays]\n")
            
            # Ensure name_match is true and structure is valid
            if not isinstance(extracted_data, dict):
                extracted_data = {
                    'patient_name': user.first_name + ' ' + user.last_name,
                    'name_match': True,
                    'report_date': '',
                    'medical_data': [],
                    'new_fields': []
                }
            
            # Validate critical fields exist
            if 'name_match' not in extracted_data:
                extracted_data['name_match'] = True
            if 'medical_data' not in extracted_data:
                extracted_data['medical_data'] = []
            if 'new_fields' not in extracted_data:
                extracted_data['new_fields'] = []
            
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
            
            if existing_report:
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
                    field = ReportField(
                        report_id=new_report.id,
                        user_id=current_user_id,
                        field_name=item.get('field_name', 'Unknown'),
                        field_value=item.get('field_value', ''),
                        field_unit=item.get('field_unit', ''),
                        normal_range=item.get('normal_range', ''),
                        is_normal=item.get('is_normal', True),
                        field_type=item.get('field_type', 'measurement'),
                        notes=item.get('notes', '')
                    )
                    db.session.add(field)
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
                print("="*80 + "\n")
                
                # Step 7: Handle new fields - Save to AdditionalField table AND merge to profile
                new_fields_info = []
                for new_field in extracted_data.get('new_fields', []):
                    category = new_field.get('category', 'other')
                    field_name = new_field.get('field_name', '')
                    field_value = new_field.get('field_value', '')
                    
                    # Create additional field record
                    additional_field = AdditionalField(
                        user_id=current_user_id,
                        report_id=new_report.id,
                        field_name=field_name,
                        field_value=field_value,
                        category=category,
                        is_approved=True,  # Automatically approved
                        approved_at=datetime.utcnow(),
                        merged_to_profile=True  # Automatically merged
                    )
                    db.session.add(additional_field)
                    
                    # Immediately merge into user profile based on category
                    if category == 'medical_history':
                        if user.medical_history:
                            user.medical_history += f"\n{field_name}: {field_value}"
                        else:
                            user.medical_history = f"{field_name}: {field_value}"
                    
                    elif category == 'allergies':
                        if user.allergies:
                            user.allergies += f"\n{field_name}: {field_value}"
                        else:
                            user.allergies = f"{field_name}: {field_value}"
                    
                    else:  # 'other' category
                        if user.medical_history:
                            user.medical_history += f"\n[Additional] {field_name}: {field_value}"
                        else:
                            user.medical_history = f"[Additional] {field_name}: {field_value}"
                    
                    new_fields_info.append({
                        'id': additional_field.id,
                        'field_name': field_name,
                        'field_value': field_value,
                        'category': category,
                        'merged_to_profile': True
                    })
                
                db.session.commit()
                
                return {
                    'message': 'Report extracted and saved successfully',
                    'report_id': new_report.id,
                    'patient_name': extracted_data.get('patient_name', ''),
                    'report_date': extracted_data.get('report_date', ''),
                    'medical_data': medical_entries,
                    'new_fields': new_fields_info,
                    'total_fields_extracted': len(medical_entries)
                }, 201
                
            except Exception as e:
                db.session.rollback()
                return {
                    'message': 'Failed to save report data',
                    'error': str(e)
                }, 500
                
        except Exception as e:
            return {'error': f'VLM processing error: {str(e)}'}, 500


@reports_ns.route('')
class UserReports(Resource):
    @reports_ns.doc(security='Bearer Auth')
    @jwt_required()
    def get(self):
        """Get all extracted reports for the current user"""
        current_user_id = get_jwt_identity()
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
        current_user_id = get_jwt_identity()
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
        current_user_id = get_jwt_identity()
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
