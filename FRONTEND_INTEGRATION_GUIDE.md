# دليل تكامل Frontend - نظام التحقق من الوصول

## نظرة عامة

عند الوصول للبيانات الطبية الحساسة (مثل التقارير الطبية)، يجب التحقق من الهوية أولاً باستخدام OTP.

## Flow كامل

```
1. المستخدم يطلب الوصول للبيانات (مثلاً: GET /profiles/5/reports)
   ↓
2. Backend يرد بـ 403 مع requires_verification: true
   ↓
3. Frontend يطلب كود التحقق (POST /auth/request-access-verification)
   ↓
4. Backend يرسل OTP إلى البريد الإلكتروني
   ↓
5. Frontend يعرض input للمستخدم لإدخال الكود
   ↓
6. المستخدم يدخل الكود
   ↓
7. Frontend يرسل الكود للتحقق (POST /auth/verify-access-code)
   ↓
8. Backend يرد بـ session_token
   ↓
9. Frontend يحفظ session_token ويستخدمه في header X-Access-Session-Token
   ↓
10. Frontend يعيد المحاولة للوصول للبيانات مع session_token
```

## Endpoints المطلوبة

### 1. طلب كود التحقق

**Endpoint:** `POST /auth/request-access-verification`

**Headers:**
```javascript
{
  "Authorization": "Bearer <JWT_TOKEN>",
  "Content-Type": "application/json"
}
```

**Request Body:**
```javascript
{
  "resource_type": "profile",  // أو "report" أو "all_reports"
  "resource_id": 5,            // ID البروفايل (اختياري)
  "method": "otp"              // حالياً فقط "otp" مدعوم
}
```

**Response (Success - 200):**
```javascript
{
  "message": "تم إرسال كود التحقق إلى بريدك الإلكتروني",
  "verification_id": 123,
  "method": "otp",
  "expires_in_minutes": 10
}
```

**Response (Error - 400/500):**
```javascript
{
  "message": "Error message here"
}
```

---

### 2. التحقق من الكود والحصول على Session Token

**Endpoint:** `POST /auth/verify-access-code`

**Headers:**
```javascript
{
  "Authorization": "Bearer <JWT_TOKEN>",
  "Content-Type": "application/json"
}
```

**Request Body:**
```javascript
{
  "resource_type": "profile",
  "resource_id": 5,
  "code": "123456"  // الكود المكون من 6 أرقام
}
```

**Response (Success - 200):**
```javascript
{
  "message": "تم التحقق بنجاح",
  "session_token": "abc123xyz...",
  "expires_in_minutes": 30,
  "instructions": "استخدم هذا الـ session token في header X-Access-Session-Token للوصول للبيانات"
}
```

**Response (Error - 400):**
```javascript
{
  "message": "كود التحقق غير صحيح"  // أو "انتهت صلاحية كود التحقق"
}
```

---

### 3. الوصول للبيانات مع Session Token

**Endpoint:** `GET /profiles/5/reports` (أو أي endpoint يتطلب التحقق)

**Headers:**
```javascript
{
  "Authorization": "Bearer <JWT_TOKEN>",
  "X-Access-Session-Token": "<SESSION_TOKEN>"  // مهم جداً!
}
```

**Response (Success - 200):**
```javascript
{
  "message": "Reports retrieved successfully",
  "profile": {...},
  "total_reports": 5,
  "reports": [...]
}
```

**Response (Error - 403):**
```javascript
{
  "message": "يتطلب التحقق من الوصول للبيانات الحساسة",
  "requires_verification": true,
  "verification_id": 123,
  "instructions": "استخدم /auth/verify-access-code مع كود التحقق المرسل إلى بريدك"
}
```

---

## أمثلة كود JavaScript/TypeScript

### مثال 1: Helper Function للتحقق من الوصول

```javascript
// utils/accessVerification.js

/**
 * طلب كود التحقق للوصول للبيانات
 */
async function requestAccessVerification(resourceType, resourceId = null) {
  const response = await fetch('/auth/request-access-verification', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${getJWTToken()}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      resource_type: resourceType,
      resource_id: resourceId,
      method: 'otp'
    })
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || 'Failed to request verification');
  }
  
  return await response.json();
}

/**
 * التحقق من الكود والحصول على session token
 */
async function verifyAccessCode(resourceType, resourceId, code) {
  const response = await fetch('/auth/verify-access-code', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${getJWTToken()}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      resource_type: resourceType,
      resource_id: resourceId,
      code: code
    })
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.message || 'Verification failed');
  }
  
  return await response.json();
}

/**
 * حفظ session token في localStorage
 */
function saveSessionToken(resourceType, resourceId, sessionToken, expiresInMinutes) {
  const key = `access_token_${resourceType}_${resourceId}`;
  const expiresAt = Date.now() + (expiresInMinutes * 60 * 1000);
  
  localStorage.setItem(key, JSON.stringify({
    token: sessionToken,
    expiresAt: expiresAt
  }));
}

/**
 * جلب session token من localStorage
 */
function getSessionToken(resourceType, resourceId) {
  const key = `access_token_${resourceType}_${resourceId}`;
  const stored = localStorage.getItem(key);
  
  if (!stored) return null;
  
  const data = JSON.parse(stored);
  
  // التحقق من انتهاء الصلاحية
  if (Date.now() > data.expiresAt) {
    localStorage.removeItem(key);
    return null;
  }
  
  return data.token;
}

/**
 * جلب البيانات مع التحقق التلقائي من الوصول
 */
async function fetchWithAccessVerification(url, resourceType, resourceId = null) {
  // محاولة جلب session token
  let sessionToken = getSessionToken(resourceType, resourceId);
  
  // إعداد headers
  const headers = {
    'Authorization': `Bearer ${getJWTToken()}`
  };
  
  if (sessionToken) {
    headers['X-Access-Session-Token'] = sessionToken;
  }
  
  // محاولة جلب البيانات
  let response = await fetch(url, { headers });
  
  // إذا كان يحتاج للتحقق
  if (response.status === 403) {
    const errorData = await response.json();
    
    if (errorData.requires_verification) {
      // طلب كود التحقق
      await requestAccessVerification(resourceType, resourceId);
      
      // إرجاع حالة خاصة للـ UI
      return {
        requiresVerification: true,
        verificationId: errorData.verification_id
      };
    }
  }
  
  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }
  
  return await response.json();
}
```

---

### مثال 2: React Component للتحقق من الوصول

```jsx
// components/AccessVerificationModal.jsx

import React, { useState } from 'react';
import { requestAccessVerification, verifyAccessCode, saveSessionToken } from '../utils/accessVerification';

function AccessVerificationModal({ 
  isOpen, 
  onClose, 
  onVerified, 
  resourceType, 
  resourceId 
}) {
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [codeSent, setCodeSent] = useState(false);

  // طلب كود التحقق عند فتح الـ modal
  React.useEffect(() => {
    if (isOpen && !codeSent) {
      requestCode();
    }
  }, [isOpen]);

  const requestCode = async () => {
    try {
      setLoading(true);
      await requestAccessVerification(resourceType, resourceId);
      setCodeSent(true);
      setError('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleVerify = async (e) => {
    e.preventDefault();
    
    if (code.length !== 6) {
      setError('الكود يجب أن يكون 6 أرقام');
      return;
    }

    try {
      setLoading(true);
      setError('');
      
      const result = await verifyAccessCode(resourceType, resourceId, code);
      
      // حفظ session token
      saveSessionToken(
        resourceType, 
        resourceId, 
        result.session_token, 
        result.expires_in_minutes
      );
      
      // إغلاق الـ modal وإعلام الـ parent
      onVerified(result.session_token);
      onClose();
      
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h2>التحقق من الوصول</h2>
        <p>تم إرسال كود التحقق إلى بريدك الإلكتروني</p>
        
        {error && <div className="error">{error}</div>}
        
        <form onSubmit={handleVerify}>
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
            placeholder="أدخل الكود المكون من 6 أرقام"
            maxLength={6}
            disabled={loading}
            autoFocus
          />
          
          <div className="button-group">
            <button type="submit" disabled={loading || code.length !== 6}>
              {loading ? 'جاري التحقق...' : 'تحقق'}
            </button>
            <button type="button" onClick={requestCode} disabled={loading}>
              إعادة إرسال الكود
            </button>
            <button type="button" onClick={onClose} disabled={loading}>
              إلغاء
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default AccessVerificationModal;
```

---

### مثال 3: استخدام في React Hook

```jsx
// hooks/useProfileReports.js

import { useState, useEffect } from 'react';
import { fetchWithAccessVerification, getSessionToken } from '../utils/accessVerification';

function useProfileReports(profileId) {
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [requiresVerification, setRequiresVerification] = useState(false);

  const fetchReports = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const url = `/profiles/${profileId}/reports`;
      const result = await fetchWithAccessVerification(
        url, 
        'profile', 
        profileId
      );
      
      if (result.requiresVerification) {
        setRequiresVerification(true);
        return;
      }
      
      setReports(result.reports || []);
      setRequiresVerification(false);
      
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (profileId) {
      fetchReports();
    }
  }, [profileId]);

  return {
    reports,
    loading,
    error,
    requiresVerification,
    refetch: fetchReports
  };
}
```

---

### مثال 4: استخدام في Component

```jsx
// components/ProfileReports.jsx

import React, { useState } from 'react';
import { useProfileReports } from '../hooks/useProfileReports';
import AccessVerificationModal from './AccessVerificationModal';

function ProfileReports({ profileId }) {
  const { reports, loading, error, requiresVerification, refetch } = useProfileReports(profileId);
  const [showVerificationModal, setShowVerificationModal] = useState(false);

  React.useEffect(() => {
    if (requiresVerification) {
      setShowVerificationModal(true);
    }
  }, [requiresVerification]);

  const handleVerified = (sessionToken) => {
    // بعد التحقق الناجح، إعادة جلب البيانات
    refetch();
  };

  if (loading) return <div>جاري التحميل...</div>;
  if (error) return <div>خطأ: {error}</div>;

  return (
    <div>
      <h2>التقارير الطبية</h2>
      
      {reports.length === 0 ? (
        <p>لا توجد تقارير</p>
      ) : (
        <ul>
          {reports.map(report => (
            <li key={report.report_id}>
              {report.report_name} - {report.report_date}
            </li>
          ))}
        </ul>
      )}
      
      <AccessVerificationModal
        isOpen={showVerificationModal}
        onClose={() => setShowVerificationModal(false)}
        onVerified={handleVerified}
        resourceType="profile"
        resourceId={profileId}
      />
    </div>
  );
}
```

---

## Error Handling

### حالات الخطأ الشائعة

1. **كود التحقق غير صحيح**
```javascript
{
  "message": "كود التحقق غير صحيح"
}
```

2. **انتهت صلاحية الكود**
```javascript
{
  "message": "انتهت صلاحية كود التحقق. يرجى طلب كود جديد"
}
```

3. **Session token منتهي**
```javascript
{
  "message": "Session token غير صالح أو منتهي الصلاحية",
  "requires_verification": true
}
```

4. **لا يوجد طلب تحقق نشط**
```javascript
{
  "message": "لم يتم العثور على طلب تحقق نشط"
}
```

---

## Best Practices

### 1. **إدارة Session Tokens**
- احفظ session tokens في localStorage مع تاريخ انتهاء الصلاحية
- تحقق من الصلاحية قبل كل request
- احذف tokens المنتهية تلقائياً

### 2. **UX Considerations**
- اعرض modal للتحقق فوراً عند الحاجة
- أظهر countdown timer للكود (10 دقائق)
- أضف زر "إعادة إرسال الكود"
- اعرض رسالة واضحة للمستخدم

### 3. **Security**
- لا تحفظ OTP codes في localStorage
- احذف session tokens عند logout
- استخدم HTTPS دائماً

### 4. **Performance**
- احفظ session tokens لتجنب طلب تحقق متكرر
- استخدم نفس session token لجميع requests في نفس الجلسة

---

## ملخص سريع

1. **عند الحاجة للوصول للبيانات:**
   - أرسل request عادي
   - إذا كان الرد 403 مع `requires_verification: true` → اعرض modal للتحقق

2. **في modal التحقق:**
   - اطلب كود التحقق (`/auth/request-access-verification`)
   - اعرض input للكود
   - أرسل الكود للتحقق (`/auth/verify-access-code`)
   - احفظ session token

3. **في الطلبات التالية:**
   - أضف header `X-Access-Session-Token` مع session token
   - استخدم نفس token حتى ينتهي (30 دقيقة)

---

## مثال كامل (Flow Chart)

```
User clicks "View Reports"
    ↓
GET /profiles/5/reports (without session token)
    ↓
Response: 403 { requires_verification: true }
    ↓
Show AccessVerificationModal
    ↓
POST /auth/request-access-verification
    ↓
OTP sent to email
    ↓
User enters code
    ↓
POST /auth/verify-access-code { code: "123456" }
    ↓
Response: { session_token: "abc123..." }
    ↓
Save session_token to localStorage
    ↓
GET /profiles/5/reports (with X-Access-Session-Token header)
    ↓
Response: 200 { reports: [...] }
    ↓
Display reports to user
```

---

## ملاحظات مهمة

- Session token صالح لمدة **30 دقيقة** فقط
- OTP code صالح لمدة **10 دقائق** فقط
- يجب إرسال session token في header `X-Access-Session-Token` (ليس في body)
- يمكن استخدام نفس session token لعدة requests في نفس الجلسة
- عند انتهاء session token، يجب طلب تحقق جديد

