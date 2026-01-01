"""
Database Migration Script: Add AccessVerification Table
This script creates the AccessVerification table for secure access to sensitive medical data.
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_access_verification():
    """Migrate database for AccessVerification support"""
    with app.app_context():
        try:
            print("🚀 Starting AccessVerification Migration...")
            
            # Create AccessVerification table
            try:
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS access_verification (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
                        resource_type VARCHAR(50) NOT NULL,
                        resource_id INTEGER,
                        verification_code VARCHAR(6),
                        verification_code_expires TIMESTAMP,
                        verification_method VARCHAR(20) DEFAULT 'otp',
                        session_token VARCHAR(255) UNIQUE NOT NULL,
                        verified_at TIMESTAMP,
                        expires_at TIMESTAMP NOT NULL,
                        ip_address VARCHAR(45),
                        user_agent VARCHAR(255),
                        verified BOOLEAN DEFAULT FALSE,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    );
                '''))
                db.session.commit()
                print("✅ Created AccessVerification table")
            except Exception as e:
                db.session.rollback()
                if 'already exists' in str(e):
                    print("ℹ️  AccessVerification table already exists")
                else:
                    print(f"⚠️  Error creating AccessVerification table: {e}")
            
            # Create indexes for better performance
            try:
                db.session.execute(text('''
                    CREATE INDEX IF NOT EXISTS idx_access_verification_user_resource 
                    ON access_verification(user_id, resource_type, resource_id);
                '''))
                db.session.execute(text('''
                    CREATE INDEX IF NOT EXISTS idx_access_verification_session_token 
                    ON access_verification(session_token);
                '''))
                db.session.execute(text('''
                    CREATE INDEX IF NOT EXISTS idx_access_verification_expires 
                    ON access_verification(expires_at);
                '''))
                db.session.commit()
                print("✅ Created indexes for AccessVerification table")
            except Exception as e:
                db.session.rollback()
                print(f"⚠️  Error creating indexes: {e}")
            
            print("\n🎉 Migration completed successfully!")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    print("=" * 80)
    print("Access Verification Migration Script")
    print("=" * 80)
    migrate_access_verification()

