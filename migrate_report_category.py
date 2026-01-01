"""
Database Migration Script: Add report_category to Report table
"""

from models import db
from app import app
from sqlalchemy import text

def migrate_report_category():
    """Add report_category column to Report table"""
    with app.app_context():
        try:
            print("🚀 Starting Report Category Migration...")
            
            # Check if column exists
            try:
                # Try to select the column to see if it exists
                db.session.execute(text("SELECT report_category FROM report LIMIT 1"))
                print("ℹ️  Column report_category already exists")
            except Exception:
                # If it fails, the column likely doesn't exist, so add it
                db.session.rollback()
                print("Adding report_category column...")
                try:
                    db.session.execute(text("ALTER TABLE report ADD COLUMN report_category VARCHAR(50) DEFAULT 'Lab Results'"))
                    db.session.commit()
                    print("✅ Added report_category column")
                except Exception as e:
                    db.session.rollback()
                    print(f"❌ Error adding column: {e}")
            
            print("✅ Migration completed successfully")
            
        except Exception as e:
            print(f"❌ Migration failed: {e}")

if __name__ == "__main__":
    migrate_report_category()
