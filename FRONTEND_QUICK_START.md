# دليل سريع للـ Frontend - نظام التحقق من الوصول

## 📋 ملخص سريع

عند الوصول للبيانات الطبية الحساسة (التقارير، البروفايلات)، يجب التحقق من الهوية أولاً.

---

## 🔄 الخطوات الأساسية

### 1️⃣ عند محاولة الوصول للبيانات

```javascript
// مثال: جلب تقارير بروفايل
const response = await fetch('/profiles/5/reports', {
  headers: {
    'Authorization': `Bearer ${jwtToken}`
  }
});
```

### 2️⃣ إذا كان الرد 403 مع requires_verification

```javascript
if (response.status === 403) {
  const data = await response.json();
  if (data.requires_verification) {
    // اعرض modal للتحقق
    showVerificationModal();
  }
}
```

### 3️⃣ طلب كود التحقق

```javascript
// POST /auth/request-access-verification
const verifyResponse = await fetch('/auth/request-access-verification', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    resource_type: 'profile',
    resource_id: 5,
    method: 'otp'
  })
});
```

**النتيجة:** سيتم إرسال OTP (6 أرقام) إلى البريد الإلكتروني

### 4️⃣ التحقق من الكود

```javascript
// POST /auth/verify-access-code
const verifyCodeResponse = await fetch('/auth/verify-access-code', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    resource_type: 'profile',
    resource_id: 5,
    code: '123456'  // الكود الذي أدخله المستخدم
  })
});

const { session_token } = await verifyCodeResponse.json();
```

### 5️⃣ استخدام Session Token

```javascript
// احفظ session token
localStorage.setItem('session_token_profile_5', session_token);

// استخدمه في الطلبات التالية
const reportsResponse = await fetch('/profiles/5/reports', {
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'X-Access-Session-Token': session_token  // مهم جداً!
  }
});
```

---

## 📝 Endpoints المطلوبة

| Endpoint | Method | الوصف |
|----------|--------|-------|
| `/auth/request-access-verification` | POST | طلب كود تحقق |
| `/auth/verify-access-code` | POST | التحقق من الكود والحصول على session token |
| `/profiles/<id>/reports` | GET | جلب التقارير (يتطلب session token) |
| `/profiles/<id>` | GET | جلب تفاصيل البروفايل (يتطلب session token) |
| `/reports?profile_id=<id>` | GET | جلب التقارير (يتطلب session token عند استخدام profile_id) |

---

## 🔑 Headers المطلوبة

### للتحقق من الوصول:
```
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json
```

### للوصول للبيانات:
```
Authorization: Bearer <JWT_TOKEN>
X-Access-Session-Token: <SESSION_TOKEN>  ← مهم جداً!
```

---

## ⚠️ ملاحظات مهمة

1. **Session Token صالح لمدة 30 دقيقة فقط**
2. **OTP Code صالح لمدة 10 دقائق فقط**
3. **يجب إرسال session token في header `X-Access-Session-Token`** (ليس في body)
4. **احفظ session token في localStorage** لتجنب طلب تحقق متكرر
5. **تحقق من انتهاء الصلاحية** قبل استخدام session token

---

## 💡 مثال كامل (React)

```jsx
import { useState } from 'react';

function ProfileReports({ profileId }) {
  const [reports, setReports] = useState([]);
  const [showVerification, setShowVerification] = useState(false);
  const [code, setCode] = useState('');

  const fetchReports = async () => {
    // جلب session token من localStorage
    const sessionToken = localStorage.getItem(`session_token_profile_${profileId}`);
    
    const response = await fetch(`/profiles/${profileId}/reports`, {
      headers: {
        'Authorization': `Bearer ${jwtToken}`,
        ...(sessionToken && { 'X-Access-Session-Token': sessionToken })
      }
    });

    if (response.status === 403) {
      const data = await response.json();
      if (data.requires_verification) {
        setShowVerification(true);
        // طلب كود التحقق
        await fetch('/auth/request-access-verification', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${jwtToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify({
            resource_type: 'profile',
            resource_id: profileId,
            method: 'otp'
          })
        });
      }
      return;
    }

    const data = await response.json();
    setReports(data.reports);
  };

  const handleVerify = async () => {
    const response = await fetch('/auth/verify-access-code', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${jwtToken}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        resource_type: 'profile',
        resource_id: profileId,
        code: code
      })
    });

    const { session_token } = await response.json();
    
    // حفظ session token
    localStorage.setItem(`session_token_profile_${profileId}`, session_token);
    
    // إعادة جلب البيانات
    setShowVerification(false);
    fetchReports();
  };

  return (
    <div>
      {showVerification && (
        <div className="verification-modal">
          <h3>التحقق من الوصول</h3>
          <p>تم إرسال كود التحقق إلى بريدك الإلكتروني</p>
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="أدخل الكود (6 أرقام)"
            maxLength={6}
          />
          <button onClick={handleVerify}>تحقق</button>
        </div>
      )}
      
      <button onClick={fetchReports}>عرض التقارير</button>
      {/* عرض التقارير */}
    </div>
  );
}
```

---

## 📚 ملفات مرجعية

- `FRONTEND_INTEGRATION_GUIDE.md` - دليل شامل مع أمثلة متقدمة
- `API_EXAMPLES.md` - أمثلة API مع cURL و JavaScript
- `ACCESS_VERIFICATION_GUIDE.md` - دليل النظام الكامل

---

## ❓ أسئلة شائعة

**س: متى يجب طلب التحقق؟**
ج: تلقائياً عند محاولة الوصول للبيانات الحساسة (التقارير الطبية)

**س: كم مرة يجب التحقق؟**
ج: مرة واحدة لكل session token (30 دقيقة)

**س: ماذا لو انتهت صلاحية session token؟**
ج: يجب طلب تحقق جديد

**س: هل يمكن استخدام نفس session token لعدة requests؟**
ج: نعم، طالما لم تنته صلاحيته (30 دقيقة)

