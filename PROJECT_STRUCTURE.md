# Project Structure

The application has been reorganized with a modular structure:

```
med_BE/
├── app.py                    # Main application entry point
├── config.py                 # Configuration and utilities
├── models.py                 # Database models
├── email_templates.py        # Email templates
├── routes/                   # Route modules
│   ├── __init__.py          # Routes package
│   ├── auth_routes.py       # Authentication endpoints
│   ├── user_routes.py       # User management endpoints
│   ├── vlm_routes.py        # VLM/AI processing endpoints
│   └── report_routes.py     # Medical reports endpoints
├── .env                      # Environment variables (not in git)
├── .env.example             # Example environment variables
└── requirements.txt         # Python dependencies
```

## File Organization

### `app.py`
Main Flask application initialization and route registration.

### `config.py`
- Application configuration (Config class)
- Email sending utilities (send_brevo_email)
- Ollama client initialization (create_ollama_client)

### `models.py`
Database models:
- User
- Report
- ReportField
- ReportData (deprecated)
- AdditionalField

### `routes/`
Each route file contains related endpoints:

#### `auth_routes.py`
- POST /auth/register
- POST /auth/login
- POST /auth/verify-email
- POST /auth/resend-verification
- POST /auth/forgot-password
- POST /auth/reset-password

#### `user_routes.py`
- GET /users/profile
- PUT /users/profile
- DELETE /users/delete-user-testing (testing only)
- POST /users/test-email (testing only)

#### `vlm_routes.py`
- POST /vlm/chat (extract medical report data)

#### `report_routes.py`
- GET /reports (list all reports)
- GET /reports/<id> (get specific report)
- DELETE /reports/<id> (delete report - testing only)

## Environment Variables

Copy `.env.example` to `.env` and fill in your actual values:

```bash
cp .env.example .env
```

Required variables:
- `DATABASE_URL` - PostgreSQL connection string
- `SECRET_KEY` - Flask secret key
- `MAIL_USERNAME` - Brevo SMTP username
- `MAIL_PASSWORD` - Brevo SMTP password
- `BREVO_API_KEY` - Brevo API key
- `SENDER_EMAIL` - Sender email address

## Running the Application

```bash
# Activate virtual environment
.venv/Scripts/Activate.ps1  # Windows PowerShell
# or
source .venv/bin/activate    # Linux/Mac

# Run the application
python app.py
```

The API will be available at http://localhost:8051
Swagger documentation at http://localhost:8051/swagger
