# Dockerfile for Flask App
FROM python:3.10-slim

WORKDIR /app

# Set proxy (but exclude internal Docker hostnames)
ENV http_proxy="http://213.244.124.19:3128"
ENV https_proxy="http://213.244.124.19:3128"
ENV ftp_proxy="http://213.244.124.19:3128"
ENV NO_PROXY="localhost,127.0.0.1,postgres,gemma-server,*.local"

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Run Flask app
CMD ["python", "app.py"]
