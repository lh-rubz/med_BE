from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import bcrypt
import os

db = SQLAlchemy()


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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_code_expires = db.Column(db.DateTime, nullable=True)
    reset_code = db.Column(db.String(6), nullable=True)
    reset_code_expires = db.Column(db.DateTime, nullable=True)
    reports = db.relationship('Report', backref='user', lazy=True, cascade='all, delete-orphan')
    
    def set_password(self, password):
        """Set new password"""
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        """Check if provided password matches current password"""
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_date = db.Column(db.DateTime, nullable=False)
    report_hash = db.Column(db.String(255), nullable=False)
    report_type = db.Column(db.String(100))
    doctor_names = db.Column(db.Text)  # Comma-separated list of doctor names
    original_filename = db.Column(db.String(255))  # Original filename for reference
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    fields = db.relationship('ReportField', backref='report', lazy=True, cascade='all, delete-orphan')
    files = db.relationship('ReportFile', backref='report', lazy=True, cascade='all, delete-orphan')
    
    def get_file_path(self):
        """Reconstruct file path from user_id and report metadata"""
        from config import Config
        if self.original_filename:
            user_folder = os.path.join(Config.UPLOAD_FOLDER, f"user_{self.user_id}")
            # Find file that matches the pattern
            if os.path.exists(user_folder):
                for filename in os.listdir(user_folder):
                    if filename.endswith(self.original_filename):
                        return os.path.join(user_folder, filename)
        return None


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
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ReportField(db.Model):
    """Generic field storage for any medical data extracted from reports"""
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    field_name = db.Column(db.String(255), nullable=False)
    field_value = db.Column(db.Text, nullable=False)
    field_unit = db.Column(db.String(100))
    normal_range = db.Column(db.String(255))
    is_normal = db.Column(db.Boolean)
    field_type = db.Column(db.String(50))
    category = db.Column(db.String(100))  # Category/section name (e.g., "DIFFERENTIAL COUNT", "BLOOD INDICES")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class AdditionalField(db.Model):
    """Track new fields that should be added to user profile"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    field_name = db.Column(db.String(120), nullable=False)
    field_value = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    is_approved = db.Column(db.Boolean, default=False)
    approved_at = db.Column(db.DateTime)
    merged_to_profile = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class ReportFile(db.Model):
    """Track uploaded files associated with reports"""
    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('report.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)  # Original uploaded name
    stored_filename = db.Column(db.String(255), nullable=False)    # Timestamped filename on disk
    file_path = db.Column(db.String(512), nullable=False)          # Full path to file
    file_hash = db.Column(db.String(64), nullable=True, index=True) # SHA256 hash of file content
    file_type = db.Column(db.String(10), nullable=False)           # Extension (jpg, pdf, etc)
    file_size = db.Column(db.Integer)                              # Size in bytes
    page_number = db.Column(db.Integer)                            # For PDF pages, null for images
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class MedicalSynonym(db.Model):
    """Store variations of medical test names mapping to a standard canonical name"""
    id = db.Column(db.Integer, primary_key=True)
    standard_name = db.Column(db.String(100), nullable=False)  # e.g., "Hemoglobin"
    synonym = db.Column(db.String(100), nullable=False, unique=True)  # e.g., "Hgb"
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

