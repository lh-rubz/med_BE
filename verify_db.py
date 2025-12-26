from app import app
from models import db
from sqlalchemy import text

with app.app_context():
    try:
        result = db.session.execute(text("SELECT to_regclass('authenticator')")).scalar()
        if result:
            print("✅ Table 'authenticator' exists.")
        else:
            print("❌ Table 'authenticator' NOT found.")
    except Exception as e:
        print(f"❌ Error checking table: {e}")
