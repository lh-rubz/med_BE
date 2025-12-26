"""
Database Migration Script: Facebook OAuth Support
This script updates the user table to support Facebook OAuth:
1. Adds facebook_id column
2. Ensures unique constraint on facebook_id
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_facebook_auth():
    """Migrate user table for Facebook OAuth"""
    with app.app_context():
        try:
            # 1. Add facebook_id column
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN facebook_id VARCHAR(255);'))
                db.session.commit()
                print("✅ Added facebook_id column")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️ facebook_id column already exists")
                else:
                    print(f"⚠️ Error adding facebook_id: {e}")

            # 2. Add unique constraint
            try:
                db.session.execute(text('ALTER TABLE "user" ADD CONSTRAINT uq_user_facebook_id UNIQUE (facebook_id);'))
                db.session.commit()
                print("✅ Added unique constraint to facebook_id")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️ unique constraint already exists")
                else:
                    print(f"⚠️ Error adding constraint: {e}")

            print("\n✅ Database schema updated for Facebook OAuth!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            print("\nManual SQL commands:")
            print('ALTER TABLE "user" ADD COLUMN facebook_id VARCHAR(255);')
            print('ALTER TABLE "user" ADD CONSTRAINT uq_user_facebook_id UNIQUE (facebook_id);')

if __name__ == '__main__':
    print("🔄 Starting Facebook OAuth migration...")
    migrate_facebook_auth()
