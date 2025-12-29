"""
Database Migration Script: Add ProfileShare Table
This script creates the ProfileShare table for the 'Care Circle' feature.
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_profile_share():
    """Migrate database for ProfileShare support"""
    with app.app_context():
        try:
            print("🚀 Starting ProfileShare Migration...")
            
            # Create ProfileShare table
            try:
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS profile_share (
                        id SERIAL PRIMARY KEY,
                        profile_id INTEGER NOT NULL REFERENCES profile(id) ON DELETE CASCADE,
                        shared_with_user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        access_level VARCHAR(20) DEFAULT 'view',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                '''))
                db.session.commit()
                print("✅ Created ProfileShare table")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️  ProfileShare table already exists")
                else:
                    print(f"⚠️  Error creating ProfileShare table: {e}")
            
            print("\n🎉 Migration completed successfully!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    print("=" * 80)
    print("PROFILE SHARE MIGRATION")
    print("=" * 80)
    migrate_profile_share()
