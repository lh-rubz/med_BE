"""
Database Migration Script: Google OAuth Support
This script updates the user table to support Google OAuth:
1. Adds google_id column
2. Makes password, last_name, date_of_birth, phone_number nullable

Run this script to update your database schema.
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_google_auth():
    """Migrate user table for Google OAuth"""
    with app.app_context():
        try:
            # 1. Add google_id column
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN google_id VARCHAR(255);'))
                db.session.commit()
                print("✅ Added google_id column")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️ google_id column already exists")
                else:
                    print(f"⚠️ Error adding google_id: {e}")

            # 2. Add unique constraint
            try:
                db.session.execute(text('ALTER TABLE "user" ADD CONSTRAINT uq_user_google_id UNIQUE (google_id);'))
                db.session.commit()
                print("✅ Added unique constraint to google_id")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️ unique constraint already exists")
                else:
                    print(f"⚠️ Error adding constraint: {e}")

            # 3. Make columns nullable
            columns = ['password', 'last_name', 'date_of_birth', 'phone_number']
            for col in columns:
                try:
                    db.session.execute(text(f'ALTER TABLE "user" ALTER COLUMN {col} DROP NOT NULL;'))
                    db.session.commit()
                    print(f"✅ Made {col} nullable")
                except Exception as e:
                    db.session.rollback()
                    print(f"⚠️ Error changing {col}: {e}")

            print("\n✅ Database schema updated for Google OAuth!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            print("\nManual SQL commands:")
            print('ALTER TABLE "user" ADD COLUMN google_id VARCHAR(255);')
            print('ALTER TABLE "user" ADD CONSTRAINT uq_user_google_id UNIQUE (google_id);')
            print('ALTER TABLE "user" ALTER COLUMN password DROP NOT NULL;')
            print('ALTER TABLE "user" ALTER COLUMN last_name DROP NOT NULL;')
            print('ALTER TABLE "user" ALTER COLUMN date_of_birth DROP NOT NULL;')
            print('ALTER TABLE "user" ALTER COLUMN phone_number DROP NOT NULL;')

if __name__ == '__main__':
    print("🔄 Starting Google OAuth migration...")
    migrate_google_auth()
