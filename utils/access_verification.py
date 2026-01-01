"""
نظام التحقق من الوصول للبيانات الحساسة
يضمن أن المستخدم مؤكد الهوية قبل الوصول للبيانات الطبية
"""
import secrets
import string
from datetime import datetime, timezone, timedelta
from flask import request
from models import db, User, AccessVerification
import hashlib


def generate_otp(length=6):
    """Generate a random OTP code"""
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def generate_session_token():
    """Generate a secure session token for verified access"""
    return secrets.token_urlsafe(32)


def create_access_verification(user_id, resource_type, resource_id=None, method='otp'):
    """
    Create a new access verification request for sensitive data
    
    Args:
        user_id: User ID
        resource_type: Resource type ('profile', 'report', 'all_reports')
        resource_id: Specific resource ID (optional)
        method: Verification method ('otp', 'password', 'webauthn')
    
    Returns:
        AccessVerification object
    """
    # Check if there's an active (non-expired) verification request
    existing = AccessVerification.query.filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=False
    ).order_by(AccessVerification.created_at.desc()).first()
    
    # If exists and not expired, return it instead of creating a new one
    if existing and existing.verification_code_expires:
        code_expires = existing.verification_code_expires
        if code_expires.tzinfo is None:
            code_expires = code_expires.replace(tzinfo=timezone.utc)
        
        if datetime.now(timezone.utc) < code_expires:
            # Active verification exists, return it (don't send new email)
            # Return a tuple: (verification, is_new)
            return existing, False
    
    # Delete any expired or old verification requests
    AccessVerification.query.filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=False
    ).delete(synchronize_session=False)
    db.session.commit()
    
    verification = AccessVerification(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verification_method=method,
        session_token=generate_session_token(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),  # 30 minutes validity
        ip_address=request.remote_addr if request else None,
        user_agent=request.headers.get('User-Agent') if request else None
    )
    
    if method == 'otp':
        verification.verification_code = generate_otp()
        verification.verification_code_expires = datetime.now(timezone.utc) + timedelta(minutes=10)  # OTP valid for 10 minutes
    
    db.session.add(verification)
    db.session.commit()
    
    # Return tuple: (verification, is_new=True)
    return verification, True


def send_verification_otp(user, verification):
    """
    Send OTP to user via email
    
    TODO: Can add SMS in the future
    """
    try:
        from flask import current_app
        from flask_mail import Message
        from config import send_brevo_email
        
        # Use Brevo API to send email
        html_content = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Medical Data Access Verification Code</h2>
            <p>Hello {user.first_name},</p>
            <p>You have requested access to sensitive medical data. Use the following code to verify:</p>
            <div style="background-color: #f0f0f0; padding: 15px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; margin: 20px 0;">
                {verification.verification_code}
            </div>
            <p style="color: #666;">This code is valid for 10 minutes only.</p>
            <p style="color: #666;">If you did not request this code, please ignore this message.</p>
        </div>
        """
        
        send_brevo_email(
            recipient_email=user.email,
            subject='Verification Code - MediScan',
            html_content=html_content
        )
    except Exception as e:
        print(f"⚠️  Failed to send verification OTP email: {str(e)}")
        # Don't raise exception so system continues even if email fails


def verify_access_code(user_id, code, resource_type, resource_id=None):
    """
    التحقق من كود OTP والموافقة على الوصول
    
    Returns:
        tuple: (success: bool, session_token: str or None, message: str)
    """
    verification = AccessVerification.query.filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=False
    ).order_by(AccessVerification.created_at.desc()).first()
    
    if not verification:
        return False, None, "No active verification request found"
    
    # Check expiration
    # Ensure verification_code_expires is timezone-aware
    code_expires = verification.verification_code_expires
    if code_expires and code_expires.tzinfo is None:
        code_expires = code_expires.replace(tzinfo=timezone.utc)
    
    if datetime.now(timezone.utc) > code_expires:
        db.session.delete(verification)
        db.session.commit()
        return False, None, "Verification code has expired. Please request a new code"
    
    # Verify code
    if verification.verification_code != code:
        return False, None, "Invalid verification code"
    
    # التحقق من IP (اختياري - يمكن تعطيله إذا كان المستخدم يستخدم VPN)
    # if verification.ip_address and verification.ip_address != request.remote_addr:
    #     return False, None, "تم طلب التحقق من عنوان IP مختلف"
    
    # الموافقة على الوصول
    verification.verified = True
    verification.verified_at = datetime.now(timezone.utc)
    db.session.commit()
    
    return True, verification.session_token, "تم التحقق بنجاح"


def verify_session_token(user_id, session_token, resource_type, resource_id=None):
    """
    التحقق من session token للوصول المصرح به
    
    Returns:
        tuple: (success: bool, verification: AccessVerification or None)
    """
    verification = AccessVerification.query.filter_by(
        user_id=user_id,
        session_token=session_token,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=True
    ).first()
    
    if not verification:
        return False, None
    
    # التحقق من انتهاء الصلاحية
    # التأكد من أن expires_at هو timezone-aware
    expires = verification.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    
    if datetime.now(timezone.utc) > expires:
        db.session.delete(verification)
        db.session.commit()
        return False, None
    
    return True, verification


def check_access_permission(user_id, resource_type, resource_id=None, require_verification=True):
    """
    التحقق من صلاحية الوصول للمورد
    يتحقق من وجود session token صالح أو يطلب التحقق
    
    Returns:
        tuple: (has_access: bool, needs_verification: bool, session_token: str or None)
    """
    if not require_verification:
        return True, False, None
    
    # البحث عن تحقق نشط
    verification = AccessVerification.query.filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=True
    ).order_by(AccessVerification.verified_at.desc()).first()
    
    if verification:
        # التأكد من أن expires_at هو timezone-aware
        expires = verification.expires_at
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        
        if datetime.now(timezone.utc) <= expires:
            return True, False, verification.session_token
    
    # لا يوجد تحقق نشط - يحتاج لتحقق جديد
    return False, True, None


def cleanup_expired_verifications():
    """حذف طلبات التحقق المنتهية الصلاحية"""
    now = datetime.now(timezone.utc)
    # جلب جميع السجلات ثم فلترتها يدوياً لتجنب مشاكل timezone
    all_verifications = AccessVerification.query.all()
    expired = []
    
    for v in all_verifications:
        # التحقق من expires_at
        if v.expires_at:
            expires = v.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                expired.append(v)
                continue
        
        # التحقق من verification_code_expires للطلبات غير المكتملة
        if not v.verified and v.verification_code_expires:
            code_expires = v.verification_code_expires
            if code_expires.tzinfo is None:
                code_expires = code_expires.replace(tzinfo=timezone.utc)
            if code_expires < now:
                expired.append(v)
    
    for v in expired:
        db.session.delete(v)
    
    db.session.commit()
    return len(expired)

