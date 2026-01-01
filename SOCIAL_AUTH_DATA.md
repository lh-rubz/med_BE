# البيانات المتاحة من Google و Facebook

## نظرة عامة

عند تسجيل الدخول عبر Google أو Facebook، يمكن جلب البيانات التالية:

## Google OAuth

### البيانات المتاحة من ID Token (دون access_token):
- ✅ **Email** - البريد الإلكتروني
- ✅ **Name** - الاسم الكامل
- ✅ **Given Name** - الاسم الأول
- ✅ **Family Name** - اسم العائلة
- ✅ **Picture** - صورة الملف الشخصي
- ❌ **Birthday** - تاريخ الميلاد (غير متوفر في ID Token)
- ❌ **Phone Number** - رقم الهاتف (غير متوفر في ID Token)

### للحصول على تاريخ الميلاد ورقم الهاتف:
1. يجب طلب الأذونات التالية في OAuth flow:
   - `https://www.googleapis.com/auth/user.birthday.read`
   - `https://www.googleapis.com/auth/user.phonenumbers.read`

2. يجب إرسال `access_token` (وليس فقط `id_token`) في الطلب إلى `/auth/google`

3. النظام سيستخدم Google People API لجلب هذه البيانات

### مثال على الطلب:
```json
{
  "id_token": "eyJhbGciOiJSUzI1NiIs...",
  "access_token": "ya29.a0AfH6SMC..."  // اختياري - مطلوب للحصول على birthday و phone
}
```

## Facebook OAuth

### البيانات المتاحة:
- ✅ **Email** - البريد الإلكتروني (إذا منح المستخدم الإذن)
- ✅ **Name** - الاسم الكامل
- ✅ **First Name** - الاسم الأول
- ✅ **Last Name** - اسم العائلة
- ✅ **Picture** - صورة الملف الشخصي
- ⚠️ **Birthday** - تاريخ الميلاد (يتطلب إذن `user_birthday`)
- ⚠️ **Phone** - رقم الهاتف (يتطلب إذن `user_phone_number`)

### الأذونات المطلوبة في Facebook App:
1. **الأذونات الأساسية (افتراضية)**:
   - `email` - للحصول على البريد الإلكتروني
   - `public_profile` - للحصول على الاسم والصورة

2. **أذونات إضافية (اختيارية)**:
   - `user_birthday` - للحصول على تاريخ الميلاد
   - `user_phone_number` - للحصول على رقم الهاتف

### كيفية طلب الأذونات في Facebook SDK:
```javascript
// مثال في JavaScript
FB.login(function(response) {
  // ...
}, {
  scope: 'email,public_profile,user_birthday,user_phone_number'
});
```

## الاستجابة من API

بعد تسجيل الدخول الناجح، ستحصل على:

```json
{
  "message": "Login successful",
  "access_token": "...",
  "user": {
    "email": "user@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "profile_image": "https://..."
  },
  "is_new_user": false,
  "missing_fields": ["date_of_birth", "phone_number"],
  "data_retrieved": {
    "email": true,
    "name": true,
    "first_name": true,
    "last_name": true,
    "picture": true,
    "birthday": false,      // false إذا لم يتم جلبه
    "phone_number": false   // false إذا لم يتم جلبه
  }
}
```

## ملاحظات مهمة

1. **Google**: 
   - ID Token لا يحتوي على تاريخ الميلاد أو رقم الهاتف
   - يجب إرسال `access_token` للحصول على هذه البيانات
   - المستخدم يجب أن يمنح الأذونات عند تسجيل الدخول

2. **Facebook**:
   - يجب طلب الأذونات (`user_birthday`, `user_phone_number`) في OAuth flow
   - حتى لو طلبت الأذونات، المستخدم قد يرفض منحها
   - إذا لم يمنح المستخدم الإذن، الحقل سيكون `null`

3. **البيانات المفقودة**:
   - إذا كانت بعض البيانات مفقودة، ستظهر في `missing_fields`
   - يمكنك طلب هذه البيانات من المستخدم لاحقاً

## استكشاف الأخطاء

إذا لم تحصل على البيانات المتوقعة:

1. **تحقق من الأذونات**: تأكد أنك طلبت الأذونات الصحيحة في OAuth flow
2. **تحقق من الـ Logs**: النظام يطبع معلومات مفصلة عن البيانات المسترجعة
3. **تحقق من الـ Response**: حقل `data_retrieved` يوضح ما تم جلبه بنجاح


