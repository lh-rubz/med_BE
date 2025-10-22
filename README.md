# med_BE

This project is a minimal Flask app with Swagger (Flask-RESTX) to test a Hugging Face VLM via the OpenAI-compatible router.

Files added:
- `app.py` - Flask application exposing a `/api/v1/chat` endpoint and Swagger UI at `/swagger`.
- `requirements.txt` - Python dependencies.

Running locally (Windows PowerShell):

1. Create a virtual environment and install dependencies

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt
```

2. Run the server

```powershell
python app.py
```

3. Open Swagger UI in your browser:

http://127.0.0.1:5000/swagger

Example requests

POST a prompt without image:

```powershell
curl -X POST "http://127.0.0.1:5000/api/v1/chat" -H "Content-Type: application/json" -d '{"prompt":"Describe the sunset over a mountain in one sentence."}'
```

POST a prompt with image:

```powershell
curl -X POST "http://127.0.0.1:5000/api/v1/chat" -H "Content-Type: application/json" -d '{"prompt":"Describe this image in one sentence.", "image_url":"https://cdn.britannica.com/61/93061-050-99147DCE/Statue-of-Liberty-Island-New-York-Bay.jpg"}'
```

Security note: The HF token is currently hardcoded in `app.py` as you requested. For real projects, store secrets in environment variables or a secrets manager.
# med_BE
