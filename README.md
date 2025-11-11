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

2. (Optional) Start the local Gemma 3 server in another shell

```powershell
uvicorn gemma_server:app --host 0.0.0.0 --port 8051
```

By default the server looks for model weights under `./models/gemma3`. Set
`GEMMA_MODEL_PATH` if you store the weights elsewhere.

3. Run the Flask API

```powershell
python app.py
```

4. Open Swagger UI in your browser:

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

## Running on the remote server with screen sessions

1. **Gemma model session** (`screen -S gemma3`)
		```bash
		docker exec -it medvlm /bin/bash
		source /root/.bashrc
		cd /medvlm
		uvicorn gemma_server:app --host 0.0.0.0 --port 8051 >> /var/log/gemma3.log 2>&1
	```
	Detach with `Ctrl+A` then `D` to keep the model server running.

2. **Application session** (`screen -S medvlm`)
	```bash
	docker exec -it medvlm /bin/bash
	source /root/.bashrc
	cd /medvlm
	git pull
	python app.py >> /var/log/med_app.log 2>&1
	```

Use `screen -ls` to verify both sessions are active and `screen -rd <name>` to
reattach later. The Flask service will automatically talk to the local Gemma
endpoint if it is healthy; otherwise it falls back to the Hugging Face router.

Security note: The HF token is currently hardcoded in `app.py` as you requested.
For real deployments, store secrets in environment variables or a secrets
manager.
# med_BE
