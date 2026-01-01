"""
Decorators للتحقق من الوصول للبيانات الحساسة
"""
from functools import wraps
from flask import request, jsonify
from flask_jwt_extended import get_jwt_identity
from utils.access_verification import (
    check_access_permission, 
    verify_session_token,
    create_access_verification,
    send_verification_otp
)
from models import User


def require_access_verification(resource_type, get_resource_id=None, require_verification=True):
    """
    Decorator للتحقق من الوصول للبيانات الحساسة
    
    Args:
        resource_type: نوع المورد ('profile', 'report', 'all_reports')
        get_resource_id: function لاستخراج resource_id من request (اختياري)
        require_verification: هل التحقق مطلوب (افتراضي: True)
    
    Usage:
        @require_access_verification('profile', lambda: request.view_args.get('id'))
        def get_profile(id):
            ...
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            current_user_id = int(get_jwt_identity())
            user = User.query.get(current_user_id)
            
            if not user:
                return {'message': 'المستخدم غير موجود'}, 404
            
            # استخراج resource_id إذا كان موجوداً
            resource_id = None
            if get_resource_id:
                try:
                    resource_id = get_resource_id()
                except:
                    pass
            
            # التحقق من وجود session token في headers
            session_token = request.headers.get('X-Access-Session-Token')
            
            if session_token:
                # التحقق من session token
                has_access, verification = verify_session_token(
                    current_user_id, 
                    session_token, 
                    resource_type, 
                    resource_id
                )
                
                if has_access:
                    # الوصول مصرح به - المتابعة
                    return f(*args, **kwargs)
            
            # لا يوجد session token صالح - التحقق من الحاجة للتحقق
            if require_verification:
                has_access, needs_verification, _ = check_access_permission(
                    current_user_id,
                    resource_type,
                    resource_id,
                    require_verification=True
                )
                
                if needs_verification:
                    # يحتاج لتحقق - إنشاء طلب تحقق جديد
                    verification = create_access_verification(
                        current_user_id,
                        resource_type,
                        resource_id,
                        method='otp'
                    )
                    
                    # إرسال OTP
                    send_verification_otp(user, verification)
                    
                    return {
                        'message': 'يتطلب التحقق من الوصول',
                        'requires_verification': True,
                        'verification_id': verification.id,
                        'method': 'otp',
                        'instructions': 'تم إرسال كود التحقق إلى بريدك الإلكتروني. استخدم endpoint /auth/verify-access لتأكيد الوصول.'
                    }, 403
            
            # لا يوجد وصول مصرح به
            return {
                'message': 'غير مصرح بالوصول. يرجى التحقق من الهوية أولاً',
                'requires_verification': True
            }, 403
        
        return decorated_function
    return decorator


def optional_access_verification(resource_type, get_resource_id=None):
    """
    Decorator اختياري للتحقق - لا يمنع الوصول لكن يسجل محاولات الوصول
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # TODO: يمكن إضافة logging هنا
            return f(*args, **kwargs)
        return decorated_function
    return decorator

