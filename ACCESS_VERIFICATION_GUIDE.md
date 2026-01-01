# دليل نظام التحقق من الوصول للبيانات الحساسة

## نظرة عامة

تم إضافة نظام تحقق متعدد الطبقات للوصول للبيانات الطبية الحساسة. هذا النظام يضمن أن المستخدم مؤكد الهوية قبل الوصول للبيانات الطبية.

## الميزات

### 1. **نظام OTP للتحقق**
- عند محاولة الوصول للبيانات الحساسة، يتم إرسال كود تحقق (6 أرقام) إلى البريد الإلكتروني
- الكود صالح لمدة 10 دقائق فقط
- بعد التحقق الناجح، يتم إصدار session token صالح لمدة 30 دقيقة

### 2. **Session Token**
- بعد التحقق الناجح، يتم إصدار session token فريد
- يجب إرسال هذا الـ token في header `X-Access-Session-Token` للوصول للبيانات
- الـ token صالح لمدة 30 دقيقة

### 3. **تتبع الأمان**
- يتم تسجيل IP address و User Agent لكل محاولة وصول
- يمكن تتبع جميع محاولات الوصول في جدول `access_verification`

## كيفية الاستخدام

### الخطوة 1: طلب التحقق من الوصول

عند محاولة الوصول للبيانات الحساسة (مثل التقارير الطبية)، ستحصل على رد:

```json
{
  "message": "يتطلب التحقق من الوصول للبيانات الحساسة",
  "requires_verification": true,
  "verification_id": 123,
  "instructions": "استخدم /auth/verify-access-code مع كود التحقق المرسل إلى بريدك"
}
```

### الخطوة 2: طلب كود التحقق (اختياري - يتم تلقائياً)

إذا أردت طلب كود تحقق يدوياً:

**Endpoint:** `POST /auth/request-access-verification`

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
```

**Body:**
```json
{
  "resource_type": "profile",
  "resource_id": 5,
  "method": "otp"
}
```

**Response:**
```json
{
  "message": "تم إرسال كود التحقق إلى بريدك الإلكتروني",
  "verification_id": 123,
  "method": "otp",
  "expires_in_minutes": 10
}
```

### الخطوة 3: التحقق من الكود والحصول على Session Token

**Endpoint:** `POST /auth/verify-access-code`

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
```

**Body:**
```json
{
  "resource_type": "profile",
  "resource_id": 5,
  "code": "123456"
}
```

**Response:**
```json
{
  "message": "تم التحقق بنجاح",
  "session_token": "abc123...",
  "expires_in_minutes": 30,
  "instructions": "استخدم هذا الـ session token في header X-Access-Session-Token للوصول للبيانات"
}
```

### الخطوة 4: استخدام Session Token للوصول للبيانات

**Endpoint:** `GET /profiles/5/reports`

**Headers:**
```
Authorization: Bearer <JWT_TOKEN>
X-Access-Session-Token: <SESSION_TOKEN>
```

**Response:** البيانات المطلوبة

## أنواع الموارد (Resource Types)

- `profile`: للوصول لبروفايل محدد
- `report`: للوصول لتقرير محدد
- `all_reports`: للوصول لجميع التقارير

## Endpoints المحدثة

### Profiles
- `GET /profiles/<id>` - يتطلب التحقق للوصول للتفاصيل
- `GET /profiles/<id>/reports` - يتطلب التحقق للوصول للتقارير

### Reports
- `GET /reports?profile_id=<id>` - يتطلب التحقق عند استخدام profile_id

## Migration

لتطبيق التغييرات على قاعدة البيانات:

```bash
python migrate_access_verification.py
```

## الأمان

1. **OTP Codes**: صالحة لمدة 10 دقائق فقط
2. **Session Tokens**: صالحة لمدة 30 دقيقة
3. **IP Tracking**: يتم تسجيل IP address لكل محاولة
4. **Auto Cleanup**: يتم حذف طلبات التحقق المنتهية تلقائياً

## ملاحظات مهمة

- Session token يجب إرساله في header `X-Access-Session-Token`
- إذا انتهت صلاحية session token، يجب طلب تحقق جديد
- يمكن طلب كود تحقق جديد في أي وقت
- النظام يدعم حالياً OTP فقط، يمكن إضافة طرق أخرى (password, webauthn) في المستقبل

