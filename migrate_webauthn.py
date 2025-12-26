"""
Database Migration Script: WebAuthn Support
This script creates the authenticator table for WebAuthn credentials.
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_webauthn():
    """Create authenticator table for WebAuthn"""
    with app.app_context():
        try:
            # Create Authenticator table
            print("🚀 Creating authenticator table...")
            
            # We use db.create_all() but that would try to create ALL tables
            # Instead, we'll use raw SQL to be safe and specific, or just rely on SQLAlchemy to create missing tables
            # if we bind just that model? No, let's use raw SQL for precision in this migration script context
            
            sql_commands = [
                """
                CREATE TABLE IF NOT EXISTS authenticator (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES "user"(id),
                    credential_id BYTEA NOT NULL UNIQUE,
                    public_key BYTEA NOT NULL,
                    sign_count INTEGER DEFAULT 0,
                    credential_device_type VARCHAR(50),
                    credential_backed_up BOOLEAN DEFAULT FALSE,
                    transports VARCHAR(255),
                    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT (now() at time zone 'utc'),
                    last_used_at TIMESTAMP WITHOUT TIME ZONE
                );
                """,
                """
                CREATE INDEX IF NOT EXISTS ix_authenticator_user_id ON authenticator (user_id);
                """
            ]
            
            for cmd in sql_commands:
                db.session.execute(text(cmd))
            
            db.session.commit()
            print("✅ WebAuthn authenticator table created!")
            
        except Exception as e:
            db.session.rollback()
            print(f"❌ Migration failed: {e}")

if __name__ == '__main__':
    print("🔄 Starting WebAuthn migration...")
    migrate_webauthn()
