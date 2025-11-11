# Medical VLM Backend - Deployment Guide

## Quick Start (Recommended)

### Prerequisites
- Docker and Docker Compose installed on the server
- Gemma-3 model weights at `/home/medvlm/models/gemma3`
- PostgreSQL container running (or use the one in docker-compose)

### Option 1: Using Docker Compose (Easiest)

```bash
cd /home/medvlm/med_BE

# Build and start all services
docker-compose up -d

# Check logs
docker-compose logs -f medvlm

# Verify services
curl http://localhost:8051/health      # Gemma server
curl http://localhost:8052/swagger     # Flask API (through port 8052)
```

###  Option 2: Manual Docker Start

```bash
# Build image
docker build -t medvlm:latest .

# Run container with proper port mappings
docker run -d \
  --name medvlm \
  -p 8051:8051 \
  -p 8052:8080 \
  -v /home/medvlm/models:/medvlm/models \
  -v /home/medvlm/med_BE:/medvlm/app \
  -e DATABASE_URL="postgresql://postgres:postgres123@postgres_med:5432/medical_db" \
  -e GEMMA_BASE_URL="http://localhost:8051/v1" \
  -e FLASK_PORT=8080 \
  -e FLASK_HOST=0.0.0.0 \
  medvlm:latest \
  /bin/bash
```

### Option 3: Screen Sessions (Original Setup)

```bash
# SSH into server
ssh medvlm@176.119.254.185

# Enter container
docker exec -it medvlm bash

# Inside container - Session 1: Gemma Server
screen -S gemma3 -d -m python3 gemma_server.py

# Inside container - Session 2: Flask API
screen -S flask_api -d -m python3 app.py

# Check running sessions
screen -ls

# Attach to a session
screen -r gemma3
# Detach with Ctrl+A, then D
```

## Port Mappings

- **Port 8051** (external) → Gemma FastAPI server (internal port 8051)
  - Access: `http://176.119.254.185:8051`
  - Endpoints: `/health`, `/v1/chat/completions`, `/swagger`

- **Port 8052** (external) → Flask API (internal port 8080)
  - Access: `http://176.119.254.185:8052`
  - Note: Port 8080 is occupied by another service, so we map to 8052

## Environment Variables

Create `.env` file in the project root:

```
DATABASE_URL=postgresql://postgres:postgres123@postgres_med:5432/medical_db
SECRET_KEY=your-secret-key-12345
GEMMA_BASE_URL=http://localhost:8051/v1
FLASK_PORT=8080
FLASK_HOST=0.0.0.0
```

## Troubleshooting

### Port Already in Use
If port 8052 is already in use, change the external port in docker-compose.yml:
```yaml
ports:
  - "8053:8080"  # Use 8053 instead
```

### Container Exits Immediately
Check logs:
```bash
docker logs medvlm
```

Ensure all dependencies are installed in Dockerfile.

### Can't Connect to Database
- Verify postgres_med container is running: `docker ps | grep postgres`
- Check DATABASE_URL environment variable is correct
- Ensure containers are on the same Docker network

### Gemma Model Not Found
Verify the model is at `/home/medvlm/models/gemma3` on the host machine and properly mounted in the container.

## Testing Services

### Test Gemma Server
```bash
curl -v http://176.119.254.185:8051/health
curl -X POST http://176.119.254.185:8051/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local-gemma-3",
    "messages": [{"role": "user", "content": "Hello"}],
    "max_tokens": 100
  }'
```

### Test Flask API
```bash
# Access Swagger UI
curl http://176.119.254.185:8052/swagger

# Register user
curl -X POST http://176.119.254.185:8052/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass123"}'

# Login
curl -X POST http://176.119.254.185:8052/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"pass123"}'
```

## Stopping Services

```bash
# Using Docker Compose
docker-compose down

# Using manual Docker
docker stop medvlm
docker rm medvlm
```

## Viewing Logs

```bash
# Docker Compose
docker-compose logs -f medvlm

# Manual Docker
docker logs -f medvlm

# Inside screen session
screen -r session_name
```

## Notes

- Both services (Gemma + Flask) run inside the same container for simplicity
- Models are mounted as read-only volumes from the host
- Application code is mounted as a volume for easy updates
- PostgreSQL runs in a separate container on the default network
