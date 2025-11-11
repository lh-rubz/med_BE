#!/bin/bash
set -e

echo "Installing dependencies..."
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-dev

echo "Installing Python requirements..."
pip install --no-cache-dir -q -r /medvlm/app/requirements.txt

echo "Creating .env file..."
cat > /medvlm/app/.env << 'EOF'
DATABASE_URL=postgresql://postgres:postgres123@10.10.0.17:5432/medical_db
SECRET_KEY=your-secret-key-12345
GEMMA_BASE_URL=http://localhost:8051/v1
FLASK_PORT=8080
FLASK_HOST=0.0.0.0
EOF

echo "All dependencies installed!"
echo "Services will be started via screen sessions."
echo "To start Gemma: screen -S gemma3 -d -m python3 /medvlm/app/gemma_server.py"
echo "To start Flask: screen -S medvlm_flask -d -m python3 /medvlm/app/app.py"
echo ""
echo "Keeping container alive..."
tail -f /dev/null
