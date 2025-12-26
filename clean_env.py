
import os
import re

def clean_env():
    valid_keys = [
        'DATABASE_URL',
        'SECRET_KEY',
        'BREVO_API_KEY',
        'SENDER_EMAIL',
        'SENDER_NAME',
        'MAIL_USE_TLS',
        'MAIL_USE_SSL',
        'GOOGLE_CLIENT_ID',
        'GOOGLE_CLIENT_SECRET'
    ]
    
    try:
        with open('.env', 'rb') as f:
            content = f.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error reading .env: {e}")
        return

    lines = content.splitlines()
    cleaned_lines = []
    seen_keys = set()

    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Simple heuristic for key=value
        match = re.match(r'^([A-Z_]+)=(.*)$', line)
        if match:
            key = match.group(1)
            if key in valid_keys:
                if key not in seen_keys:
                    cleaned_lines.append(line)
                    seen_keys.add(key)
                else:
                    # If key valid but already seen, maybe keep the last one? or first?
                    # Usually last one wins in dotenv, but let's keep the first valid one we find to avoid duplicates in file
                    # Actually, if I just appended the google ones, they are at the end.
                    # If the file had garbage, maybe previous keys were okay.
                    pass
            else:
                 # Check if it looks like a valid env var anyway
                 pass

    # Manually ensure our keys are present (in case they were filtered out by garbage or missing)
    # Re-reading what I deduced earlier might be risky if I mess up.
    # But I can trust the `lines` contains what I need.
    
    # If the file was so corrupted that lines aren't splitting correctly, this might fail.
    # But `findstr` found BREVO_API_KEY on a line.
    
    # Let's just output what we found to verify before writing.
    for line in cleaned_lines:
        print(line)

if __name__ == '__main__':
    clean_env()
