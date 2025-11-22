# Server Environment Variables Setup Guide

This document lists all the environment variables you need to configure on your server to run the Medical Application.

## Required Environment Variables

### 1. Database Configuration
```bash
DATABASE_URL=postgresql://username:password@host:port/database_name
```
- Replace with your PostgreSQL database connection string
- Example: `postgresql://medapp_user:securepass123@db.example.com:5432/meddb`

### 2. Application Security
```bash
SECRET_KEY=your_very_secure_random_string_here
```
- Generate a strong random key for JWT token encryption
- You can generate one using: `python -c "import secrets; print(secrets.token_urlsafe(32))"`

### 3. Email Configuration (Brevo SMTP)
```bash
MAIL_SERVER=smtp-relay.brevo.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USE_SSL=False
MAIL_USERNAME=9c0810001@smtp-brevo.com
MAIL_PASSWORD=your_brevo_api_key_here
MAIL_DEFAULT_SENDER=9c0810001@smtp-brevo.com
```

**Important:** 
- `MAIL_PASSWORD` should be your Brevo SMTP API key (not your Brevo account password)
- You can find your SMTP API key in your Brevo account under: Settings → SMTP & API → SMTP Keys
- Create a new SMTP key if you don't have one

### 4. Ollama/VLM Configuration (Optional)
```bash
OLLAMA_BASE_URL=http://localhost:11434/v1
OLLAMA_MODEL=gemma3:4b
```
- These are for the AI vision model used for medical report extraction
- If running Ollama on a different server, update the URL accordingly

## How to Set Up on Your Server

### Option 1: Using .env file
1. Create a `.env` file in the project root directory
2. Copy the content from `.env.example`
3. Fill in all the values with your actual credentials

### Option 2: Setting Environment Variables Directly
Depending on your server setup:

**Linux/Unix:**
```bash
export DATABASE_URL="postgresql://..."
export SECRET_KEY="your_secret_key"
export MAIL_PASSWORD="your_brevo_api_key"
# ... etc
```

**Windows:**
```powershell
$env:DATABASE_URL="postgresql://..."
$env:SECRET_KEY="your_secret_key"
$env:MAIL_PASSWORD="your_brevo_api_key"
# ... etc
```

**Docker:**
Add to your `docker-compose.yml`:
```yaml
environment:
  - DATABASE_URL=postgresql://...
  - SECRET_KEY=your_secret_key
  - MAIL_PASSWORD=your_brevo_api_key
```

### Option 3: Cloud Platform Configuration
- **Heroku:** Use the Config Vars section in Settings
- **AWS Elastic Beanstalk:** Use environment properties
- **Google Cloud:** Use environment variables in app.yaml
- **Azure:** Use Application Settings

## Security Best Practices

1. **Never commit `.env` file to git** - it's already in `.gitignore`
2. **Use strong, unique passwords** for database and secret key
3. **Keep your Brevo API key secure** - treat it like a password
4. **Use different credentials** for development and production
5. **Rotate credentials regularly**, especially if compromised

## New Features Added

### Email Verification
- Users receive a verification email upon registration
- Must verify email before logging in
- Endpoint: `POST /auth/verify-email`

### Password Reset
- Users can request password reset via email
- Token expires after 1 hour
- Endpoints:
  - `POST /auth/forgot-password` - Request reset
  - `POST /auth/reset-password` - Reset with token

## Testing Email Functionality

To test that email is working:
1. Register a new user
2. Check if verification email is received
3. Use the token from email to verify
4. Try forgot password flow

## Troubleshooting

### Emails not sending?
- Verify `MAIL_USERNAME` and `MAIL_PASSWORD` are correct
- Check Brevo account is active and not suspended
- Verify SMTP key has not been revoked
- Check server firewall allows outbound connections on port 587

### Database connection issues?
- Verify `DATABASE_URL` format is correct
- Check database server is accessible from your application server
- Verify database credentials are correct
- Ensure PostgreSQL is running

## Support

For Brevo SMTP issues, refer to:
- Brevo Documentation: https://developers.brevo.com/docs
- Brevo Support: https://help.brevo.com/
