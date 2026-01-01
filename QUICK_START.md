# دليل سريع - كيف تجيب البيانات

## 🎯 الهدف
جلب: **الاسم**، **تاريخ الميلاد**، **رقم الهاتف** من Google و Facebook

---

## 🔵 Google

### المشكلة:
- `id_token` يعطيك: ✅ email, name, picture
- لكن **ما** يعطيك: ❌ birthday, phone_number

### الحل:
**أرسل `access_token` إضافي مع `id_token`**

### الخطوات:

#### 1. في تطبيقك (Android/iOS/Web):
عند تسجيل الدخول، احصل على `access_token` أيضاً (مش بس `id_token`)

#### 2. أرسل للـ Backend:
```json
POST /auth/google
{
  "id_token": "...",        // ✅ موجود
  "access_token": "..."     // ⚠️ أضف هذا!
}
```

#### 3. النتيجة:
الـ backend راح يجيب birthday و phone_number من Google People API تلقائياً ✅

---

## 🔵 Facebook

### المشكلة:
- `access_token` يعطيك: ✅ email, name, picture
- لكن **ما** يعطيك: ❌ birthday, phone_number (إلا إذا طلبت الأذونات)

### الحل:
**اطلب الأذونات عند تسجيل الدخول**

### الخطوات:

#### 1. في تطبيقك (Android/iOS/Web):
عند تسجيل الدخول، طالب بالأذونات التالية:

**Android:**
```kotlin
val permissions = listOf(
    "email",
    "public_profile",
    "user_birthday",        // ⚠️ مهم!
    "user_phone_number"      // ⚠️ مهم!
)
```

**iOS:**
```swift
loginManager.logIn(permissions: [
    "email",
    "public_profile",
    "user_birthday",
    "user_phone_number"
], from: self)
```

**Web:**
```javascript
FB.login(function(response) {
    // ...
}, {
    scope: 'email,public_profile,user_birthday,user_phone_number'  // ⚠️ مهم!
});
```

#### 2. أرسل للـ Backend:
```json
POST /auth/facebook
{
  "access_token": "..."  // ✅ هذا كافي
}
```

#### 3. النتيجة:
الـ backend راح يجيب birthday و phone_number (إذا المستخدم وافق) ✅

---

## ✅ كيف تعرف إذا البيانات وصلت؟

بعد تسجيل الدخول، الـ backend بيرجعلك:

```json
{
  "data_retrieved": {
    "email": true,
    "name": true,
    "birthday": true,        // ✅ إذا وصل
    "phone_number": true     // ✅ إذا وصل
  },
  "missing_fields": []      // ✅ فارغ = كل شي وصل
}
```

---

## 📋 Checklist

### Google:
- [ ] أرسلت `id_token` ✅
- [ ] أرسلت `access_token` أيضاً ⚠️
- [ ] المستخدم منح الأذونات ✅

### Facebook:
- [ ] طلبت permission `user_birthday` ⚠️
- [ ] طلبت permission `user_phone_number` ⚠️
- [ ] أرسلت `access_token` ✅
- [ ] المستخدم وافق على الأذونات ✅

---

## 🔍 إذا البيانات ما وصلت

1. **شوف الـ logs في الـ backend** - راح يطبعلك شو وصل
2. **شوف `data_retrieved` في الـ response** - راح يخبرك شو موجود
3. **تأكد من الأذونات** - Google يحتاج `access_token`، Facebook يحتاج permissions

---

## 📞 أمثلة كود كاملة

شوف الملفات:
- `CODE_EXAMPLES.md` - أمثلة كود لكل منصة
- `HOW_TO_GET_DATA.md` - شرح تفصيلي


