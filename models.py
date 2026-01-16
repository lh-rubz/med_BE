from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
import bcrypt
import os

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=True)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=True)
    date_of_birth = db.Column(db.Date, nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    gender = db.Column(db.String(20))
    profile_image = db.Column(db.String(255), default='default.jpg')  # Filename of profile image
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)
    email_verified = db.Column(db.Boolean, default=False)
    biometric_allowed = db.Column(db.Boolean, default=True)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_code_expires = db.Column(db.DateTime, nullable=True)
    reset_code = db.Column(db.String(255), nullable=True)  # Increased to support secure tokens
    reset_code_expires = db.Column(db.DateTime, nullable=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    facebook_id = db.Column(db.String(255), unique=True, nullable=True)
    # Two-Factor Authentication (2FA)
    two_factor_enabled = db.Column(db.Boolean, default=False)
    two_factor_code = db.Column(db.String(6), nullable=True)  # OTP code for 2FA
    two_factor_code_expires = db.Column(db.DateTime, nullable=True)  # OTP expiration time
    authenticators = db.relationship('Authenticator', backref='user', lazy=True, cascade='all, delete-orphan')
    reports = db.relationship('Report', backref='user', lazy=True, cascade='all, delete-orphan')
    profiles = db.relationship('Profile', backref='owner', lazy=True, foreign_keys='Profile.creator_id', cascade='all, delete-orphan')
    
    # Connections where this user is the one who requested access
    connections_sent = db.relationship('FamilyConnection', backref='requester', lazy=True, foreign_keys='FamilyConnection.requester_id')
    # Connections where this user is the one receiving the request
    connections_received = db.relationship('FamilyConnection', backref='receiver', lazy=True, foreign_keys='FamilyConnection.receiver_id')
    
    def set_password(self, password):
        """Set new password"""
        self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def check_password(self, password):
        """Check if provided password matches current password"""
        if not self.password:
            return False
        return bcrypt.checkpw(password.encode('utf-8'), self.password.encode('utf-8'))


class Report(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    profile_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=True) # Linked to a specific family profile
    report_date = db.Column(db.DateTime, nullable=False)
    report_hash = db.Column(db.String(255), nullable=False)
    report_name = db.Column(db.String(255)) # Specific title e.g. "Detailed Hemogram"
    report_type = db.Column(db.String(100)) # Standard category e.g. "Complete Blood Count (CBC)"
    report_category = db.Column(db.String(50), default='Lab Results') # High-level category: Lab Results, Imaging, Prescriptions, etc.
    patient_name = db.Column(db.String(255)) # Extracted patient name
    patient_age = db.Column(db.String(50))    # e.g. "45 years", "2 months"
    patient_gender = db.Column(db.String(20)) # e.g. "Male", "Female"
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

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Authenticator(db.Model):
    """Store WebAuthn/Passkey credentials"""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    credential_id = db.Column(db.LargeBinary, unique=True, nullable=False)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.Integer, default=0)
    credential_device_type = db.Column(db.String(50), nullable=True) # e.g. 'single_device' or 'multi_device' (synced)
    credential_backed_up = db.Column(db.Boolean, default=False)
    transports = db.Column(db.String(255), nullable=True) # comma-separated list of transports
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = db.Column(db.DateTime, nullable=True)


class Profile(db.Model):
    """Managed profiles for family members (e.g., children, parents)"""
    id = db.Column(db.Integer, primary_key=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # The account owner
    linked_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # If this profile belongs to another registered user
    
    __table_args__ = (
        db.Index('idx_unique_self_profile', 'creator_id', 'relationship', unique=True, postgresql_where=db.text("relationship = 'Self'")),
    )
    
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50))
    date_of_birth = db.Column(db.Date)
    gender = db.Column(db.String(20))
    relationship = db.Column(db.String(50), default='Self') # Relationship to creator (Self, Son, Father, etc.)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    reports = db.relationship('Report', backref='profile', lazy=True)

    # Prevent circular reference issues by using explicit backref names if needed
    linked_user = db.relationship('User', foreign_keys=[linked_user_id], backref='linked_profiles', lazy=True)

    # Add cascade delete to shares
    # defined in ProfileShare.profile backref, but can be explicit here if needed.
    # The backref in ProfileShare is: db.relationship('Profile', backref=db.backref('shares', lazy=True))
    # We should update that instead to include cascade.


class FamilyConnection(db.Model):
    """Links between two existing user accounts (e.g., Mother <-> Elderly Father)"""
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    relationship = db.Column(db.String(50), nullable=False) # Relationship of receiver to requester
    status = db.Column(db.String(20), default='pending') # pending, accepted, rejected
    access_level = db.Column(db.String(20), default='view') # view, manage (can upload)
    
    # NEW: Optional link to a specific profile being shared
    profile_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, onupdate=lambda: datetime.now(timezone.utc))


class ProfileShare(db.Model):
    """Tracks access grants to specific profiles (e.g., Mom shares 'Son' with Dad)"""
    id = db.Column(db.Integer, primary_key=True)
    profile_id = db.Column(db.Integer, db.ForeignKey('profile.id'), nullable=False)
    shared_with_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # 'view' = read-only, 'upload' = read+write, 'manage' = full control
    access_level = db.Column(db.String(20), default='view', nullable=False) 
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationships
    # Note: We use overlaps to avoid conflicts if multiple relationships point to the same table
    profile = db.relationship('Profile', backref=db.backref('shares', lazy=True, cascade='all, delete-orphan'))
    shared_with = db.relationship('User', foreign_keys=[shared_with_user_id], backref=db.backref('received_shares', lazy=True))


class AccessVerification(db.Model):
    """
    نظام التحقق من الوصول للبيانات الحساسة
    يطلب تأكيد إضافي (OTP أو re-authentication) قبل الوصول للبيانات الطبية
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    resource_type = db.Column(db.String(50), nullable=False)  # 'profile', 'report', 'all_reports'
    resource_id = db.Column(db.Integer, nullable=True)  # ID of the specific resource (profile_id, report_id, etc.)
    
    # OTP verification
    verification_code = db.Column(db.String(6), nullable=True)  # 6-digit OTP
    verification_code_expires = db.Column(db.DateTime, nullable=True)
    verification_method = db.Column(db.String(20), default='otp')  # 'otp', 'password', 'webauthn'
    
    # Session tracking
    session_token = db.Column(db.String(255), unique=True, nullable=False)  # Unique token for this access session
    verified_at = db.Column(db.DateTime, nullable=True)  # When verification was completed
    expires_at = db.Column(db.DateTime, nullable=False)  # When this verification session expires
    
    # Security tracking
    ip_address = db.Column(db.String(45), nullable=True)  # IPv4 or IPv6
    user_agent = db.Column(db.String(255), nullable=True)
    verified = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    
    # Relationship
    user = db.relationship('User', backref=db.backref('access_verifications', lazy=True))


class Notification(db.Model):
    """
    Stores in-app notification history for users.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=False) # report_upload, profile_share
    is_read = db.Column(db.Boolean, default=False)
    data = db.Column(db.JSON, nullable=True) # Store extra data like profile_id, report_id
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))


class UserDevice(db.Model):
    """
    Stores FCM tokens for user devices to send push notifications.
    """
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fcm_token = db.Column(db.String(512), nullable=False) # Firebase Cloud Messaging Token
    device_type = db.Column(db.String(50), nullable=True) # android, ios, web
    last_active = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('devices', lazy=True, cascade='all, delete-orphan'))
