# API Examples - Access Verification

## Quick Reference

### 1. Request Access Verification

```bash
POST /auth/request-access-verification
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

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

---

### 2. Verify Access Code

```bash
POST /auth/verify-access-code
Authorization: Bearer <JWT_TOKEN>
Content-Type: application/json

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
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_in_minutes": 30,
  "instructions": "استخدم هذا الـ session token في header X-Access-Session-Token للوصول للبيانات"
}
```

---

### 3. Access Protected Data

```bash
GET /profiles/5/reports
Authorization: Bearer <JWT_TOKEN>
X-Access-Session-Token: <SESSION_TOKEN>
```

**Response:**
```json
{
  "message": "Reports retrieved successfully",
  "profile": {
    "id": 5,
    "first_name": "أحمد",
    "last_name": "محمد"
  },
  "total_reports": 3,
  "reports": [...]
}
```

---

## cURL Examples

### Request Verification Code
```bash
curl -X POST http://localhost:5000/auth/request-access-verification \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "resource_type": "profile",
    "resource_id": 5,
    "method": "otp"
  }'
```

### Verify Code
```bash
curl -X POST http://localhost:5000/auth/verify-access-code \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "resource_type": "profile",
    "resource_id": 5,
    "code": "123456"
  }'
```

### Access Reports with Session Token
```bash
curl -X GET http://localhost:5000/profiles/5/reports \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "X-Access-Session-Token: YOUR_SESSION_TOKEN"
```

---

## JavaScript Fetch Examples

### Request Verification
```javascript
const response = await fetch('/auth/request-access-verification', {
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

const data = await response.json();
console.log(data);
```

### Verify Code
```javascript
const response = await fetch('/auth/verify-access-code', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    resource_type: 'profile',
    resource_id: 5,
    code: '123456'
  })
});

const data = await response.json();
const sessionToken = data.session_token;
```

### Access Data
```javascript
const response = await fetch('/profiles/5/reports', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${jwtToken}`,
    'X-Access-Session-Token': sessionToken
  }
});

const reports = await response.json();
console.log(reports);
```

---

## Error Responses

### Invalid Code
```json
{
  "message": "كود التحقق غير صحيح"
}
```

### Expired Code
```json
{
  "message": "انتهت صلاحية كود التحقق. يرجى طلب كود جديد"
}
```

### Requires Verification
```json
{
  "message": "يتطلب التحقق من الوصول للبيانات الحساسة",
  "requires_verification": true,
  "verification_id": 123,
  "instructions": "استخدم /auth/verify-access-code مع كود التحقق المرسل إلى بريدك"
}
```

### Invalid Session Token
```json
{
  "message": "Session token غير صالح أو منتهي الصلاحية",
  "requires_verification": true
}
```

