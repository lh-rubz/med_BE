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
    إنشاء طلب تحقق جديد للوصول للبيانات الحساسة
    
    Args:
        user_id: ID المستخدم
        resource_type: نوع المورد ('profile', 'report', 'all_reports')
        resource_id: ID المورد المحدد (اختياري)
        method: طريقة التحقق ('otp', 'password', 'webauthn')
    
    Returns:
        AccessVerification object
    """
    # حذف أي طلبات تحقق سابقة غير مكتملة لهذا المستخدم والمورد
    AccessVerification.query.filter_by(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verified=False
    ).delete()
    
    verification = AccessVerification(
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        verification_method=method,
        session_token=generate_session_token(),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=30),  # 30 دقيقة صلاحية
        ip_address=request.remote_addr if request else None,
        user_agent=request.headers.get('User-Agent') if request else None
    )
    
    if method == 'otp':
        verification.verification_code = generate_otp()
        verification.verification_code_expires = datetime.now(timezone.utc) + timedelta(minutes=10)  # OTP صالح لمدة 10 دقائق
    
    db.session.add(verification)
    db.session.commit()
    
    return verification


def send_verification_otp(user, verification):
    """
    إرسال OTP للمستخدم عبر البريد الإلكتروني
    
    TODO: يمكن إضافة SMS في المستقبل
    """
    try:
        from flask import current_app
        from flask_mail import Message
        from config import send_brevo_email
        
        # استخدام Brevo API لإرسال البريد
        html_content = f"""
        <div dir="rtl" style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>كود التحقق للوصول للبيانات الطبية</h2>
            <p>مرحباً {user.first_name},</p>
            <p>لقد طلبت الوصول للبيانات الطبية الحساسة. استخدم الكود التالي للتحقق:</p>
            <div style="background-color: #f0f0f0; padding: 15px; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; margin: 20px 0;">
                {verification.verification_code}
            </div>
            <p style="color: #666;">هذا الكود صالح لمدة 10 دقائق فقط.</p>
            <p style="color: #666;">إذا لم تطلب هذا الكود، يرجى تجاهل هذه الرسالة.</p>
        </div>
        """
        
        send_brevo_email(
            recipient_email=user.email,
            subject='كود التحقق - MediScan',
            html_content=html_content
        )
    except Exception as e:
        print(f"⚠️  Failed to send verification OTP email: {str(e)}")
        # لا نرفع exception لأن النظام يجب أن يستمر حتى لو فشل إرسال البريد


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
        return False, None, "لم يتم العثور على طلب تحقق نشط"
    
    # التحقق من انتهاء الصلاحية
    if datetime.now(timezone.utc) > verification.verification_code_expires:
        db.session.delete(verification)
        db.session.commit()
        return False, None, "انتهت صلاحية كود التحقق. يرجى طلب كود جديد"
    
    # التحقق من الكود
    if verification.verification_code != code:
        return False, None, "كود التحقق غير صحيح"
    
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
    if datetime.now(timezone.utc) > verification.expires_at:
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
    
    if verification and datetime.now(timezone.utc) <= verification.expires_at:
        return True, False, verification.session_token
    
    # لا يوجد تحقق نشط - يحتاج لتحقق جديد
    return False, True, None


def cleanup_expired_verifications():
    """حذف طلبات التحقق المنتهية الصلاحية"""
    now = datetime.now(timezone.utc)
    expired = AccessVerification.query.filter(
        (AccessVerification.expires_at < now) | 
        ((AccessVerification.verified == False) & (AccessVerification.verification_code_expires < now))
    ).all()
    
    for v in expired:
        db.session.delete(v)
    
    db.session.commit()
    return len(expired)

