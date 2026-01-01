"""
Script to ensure all database tables exist.
"""
from app import app, db

def ensure_tables():
    with app.app_context():
        print("🚀 Checking and creating missing tables...")
        db.create_all()
        print("✅ Database tables verified/created.")

if __name__ == "__main__":
    ensure_tables()
